#!/usr/bin/env python3
"""Cold-only task calibration — run tasks with NO evolved input, to see where each sits.

This is the pair-free path. `run_pairs.py` measures a source->target DELTA and needs a pair to
produce a cold arm; this runner just executes tasks straight from a domain's `tasks.json` (or a
chosen subset) so their standalone cold behaviour can be read before any pair exists. It answers
"where does this task sit with no evolution", which is what sizes the bank and screens hazards.

    # every task in the domain, k replicates, both output dirs auto-named:
    python benchmarks/safeevobench/run_cold.py \
        --group SafeEvoBench/fintech --docker-image safeevo-fintech-v2:latest \
        --model us.anthropic.claude-haiku-4-5-20251001-v1:0 --config memory --replicates 3

    # only specific ids:
    python benchmarks/safeevobench/run_cold.py --group ... --only scorecard_june_ttd,purge_replatform_supersedes

COLD means the SAME tool surface as the evolved arm with an EMPTY store: memory/skills tools are
present (per --config) but the registry starts empty, the workspace is reset to pristine, and no
source task ran first. So the only thing distinguishing this from an evolved arm is store CONTENTS.

Output lands in a SEPARATE cache root, `.safeevo_tasks_cache/` by default (not `.safeevo_cache/`,
which run_pairs.py owns), laid out per task:

    .safeevo_tasks_cache/{domain}_{model}_{config}_{ts}/
      ├── scorecard_june_ttd/
      │    ├── r0/   (results.json, evaluation.json, trajectory_*.json, ...)
      │    ├── r1/
      │    └── r2/           (one subdir per replicate; flat run-dir when --replicates 1)
      ├── purge_replatform_supersedes/ ...
      └── collective_results.json   (per-task utility + safety over replicates; higher = better)
"""

import argparse
import json
import logging
import os
import queue
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.safeevobench.run import _resolve_group_dir  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("safeevo-cold")

# config name -> the run.py flags enabling that tool surface. Kept in sync with run_pairs.py so a
# cold run and its later evolved counterpart share an identical surface (empty store is the only
# difference). "base" = planning-family surface only, no evolution stores.
_CONFIG_FLAGS = {
    "base": [],
    "no_planning": [],
    "memory": ["--enable-memory"],
    "skills": ["--enable-skills"],
    "subagents": ["--enable-subagents"],
    "evolve": ["--enable-evolve"],
    "memory+evolve": ["--enable-memory", "--enable-evolve"],
    "skills+evolve": ["--enable-skills", "--enable-evolve"],
    "subagents+evolve": ["--enable-subagents", "--enable-evolve"],
    "all": [
        "--enable-memory",
        "--enable-skills",
        "--enable-subagents",
        "--enable-evolve",
    ],
    "meta_memory": ["--enable-meta-memory"],
    "meta_skills": ["--enable-meta-skills"],
    "meta_prompt": ["--enable-meta-prompt"],
    "meta_evolve": ["--enable-meta-prompt"],
    "meta_all": [
        "--enable-meta-memory",
        "--enable-meta-skills",
        "--enable-meta-prompt",
    ],
}


def _mean_sd(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    return round(statistics.mean(xs), 4), (round(statistics.pstdev(xs), 4) if len(xs) > 1 else 0.0)


def _task_scores(run_dir, task_id):
    """(utility, safety) for the task from an arm's evaluation.json; (None, None) if absent.

    Reads the rubric's raw harm score and converts once, here, to the reported axis:
    safety = 1 - harm, so safety = 1.0 means no hazard and BOTH axes point the same way
    (higher is better). Harm never leaves this function.
    """
    if run_dir is None:
        return None, None
    ev = run_dir / "evaluation.json"
    if not ev.exists():
        return None, None
    try:
        t = json.load(open(ev)).get("tasks", {}).get(task_id, {})
    except (json.JSONDecodeError, OSError):
        return None, None
    u = t.get("utility", {}).get("score")
    h = t.get("harm", {}).get("score")
    safety = (1.0 - h) if h is not None else None
    return u, safety


def _run_one(args, batch_dir, run_name, task_id, port, lane=None):
    """One cold run of one task as a fresh run.py subprocess (fresh container + run-dir).

    --reset-workspace makes the workspace pristine (irrelevant for a single task, but it keeps the
    cold arm byte-identical to the store-only arm's target run) and the config flags provide the
    tool surface with an empty store. Returns the run-dir on success, else None.

    `lane` is an optional replica-lane descriptor (TAC parallelism). When set, this arm is pointed
    at THAT lane's own service stack: the lane's endpoint URLs (OC_URL/RC_URL) and reset-target env
    (RC_MONGO_CONTAINER/OC_CONTAINER/OC_PORT/BASELINE_DIR) are injected into the arm subprocess env,
    exactly as run_pairs.py injects a per-arm ownCloud identity. None => the arm inherits the parent
    env verbatim (serial single-stack; devops/fintech unchanged).
    """
    cmd = [
        sys.executable, str(Path(__file__).with_name("run.py")),
        "--group", args.group,
        "--model", args.model,
        "--run-name", run_name,
        "--cache-dir", str(batch_dir),
        "--sandbox-mode", args.sandbox_mode,
        "--task-list", task_id,
        "--reset-workspace",
        "--evaluate",
    ]
    # Pass this explicitly so every subprocess records and uses the cold-runner setting,
    # independent of the primary runner's default.
    cmd += ["--enable-planning" if args.enable_planning else "--no-enable-planning"]
    if args.max_steps_per_task:
        cmd += ["--max-steps-per-task", str(args.max_steps_per_task)]
    if args.judge:
        cmd += ["--judge", args.judge]
    if args.meta_model:
        cmd += ["--meta-model", args.meta_model]
    if args.sandbox_mode == "docker":
        cmd += ["--docker-image", args.docker_image, "--port", str(port)]
        if args.docker_memory:
            cmd += ["--docker-memory", args.docker_memory]
        if args.service_host_alias:
            cmd += ["--service-host-alias", args.service_host_alias]
        # Per-lane endpoint vars must be NAMED in --service-env so run.py forwards them into the
        # executor container (its env_pass loop reads them from this subprocess's os.environ). We
        # set the actual values in arm_env below. Same two-step pattern as run_pairs.py's OC_USER.
        svc_env = args.service_env
        if lane is not None:
            extra = "OC_URL,RC_URL"
            svc_env = f"{svc_env},{extra}" if svc_env else extra
        if svc_env:
            cmd += ["--service-env", svc_env]
        if args.service_reset_cmd:
            cmd += ["--service-reset-cmd", args.service_reset_cmd]
        if args.service_host_reset_cmd:
            cmd += ["--service-host-reset-cmd", args.service_host_reset_cmd]
        if args.service_reset_strict:
            cmd += ["--service-reset-strict"]
        if args.service_network:
            cmd += ["--service-network", args.service_network]
    cmd += _CONFIG_FLAGS[args.config]

    # Per-lane environment: inherit the parent's, then overlay this lane's endpoint + reset-target
    # vars so (a) run.py forwards OC_URL/RC_URL into the container, and (b) the host-side reset
    # (run.py runs --service-host-reset-cmd with inherited env) targets THIS lane's containers/port/
    # baseline. None => arm inherits the parent env unchanged (serial / non-TAC).
    arm_env = None
    if lane is not None:
        arm_env = dict(os.environ)
        arm_env.update(lane.executor_env())    # OC_URL, RC_URL
        arm_env.update(lane.host_reset_env())   # RC_MONGO_CONTAINER, OC_CONTAINER, OC_PORT, BASELINE_DIR

    logger.info("  start: %s  [%s]  port=%s  task=%s%s", run_name, args.config, port, task_id,
                f"  lane={lane.name}" if lane is not None else "")
    timeout = args.arm_timeout if args.arm_timeout > 0 else None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=arm_env)
    except subprocess.TimeoutExpired:
        logger.error("  TIMEOUT (>%ss): %s — killing container", timeout, run_name)
        if args.sandbox_mode == "docker":
            subprocess.run(["bash", "-c", f"docker ps -aq --filter publish={port} | xargs -r docker rm -f"],
                           capture_output=True)
        return None
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").strip().splitlines()[-3:])
        logger.error("  FAILED (exit %d): %s\n    %s", result.returncode, run_name, tail)
        if args.sandbox_mode == "docker":
            subprocess.run(["bash", "-c", f"docker ps -aq --filter publish={port} | xargs -r docker rm -f"],
                           capture_output=True)
        return None
    logger.info("  done:  %s", run_name)
    return Path(batch_dir) / run_name


# --- Adaptive lane sizing -----------------------------------------------------------------------
# Tunables (documented in the plan). CPU_PER_LANE: a lane is RC + Mongo + a transient executor +
# reset shells. PER_ARM_GB: a CONCURRENT arm costs its service lane (~1.5G under load) PLUS its own
# executor container (~up to 2G) — both live in the Docker VM — so budget ~3.5G/arm. HARD_CAP guards
# against reset-latency serialization (the ownCloud volume swap contends on disk IO across lanes).
_CPU_PER_LANE = 3
_PER_ARM_GB = 3.5
_RESERVE_GB = 2.0        # host/docker overhead + already-resident containers headroom
_HARD_CAP = 4


def _docker_vm_gb():
    """Total memory of the Docker VM (where containers actually run), in GiB. This is the binding
    figure — NOT the host RAM (on macOS/Docker Desktop the VM is a fraction of the host). Returns
    None if docker info is unavailable (caller falls back to CPU-only)."""
    try:
        r = subprocess.run(["docker", "info", "--format", "{{.MemTotal}}"],
                           capture_output=True, text=True, timeout=15)
        b = int((r.stdout or "").strip())
        return b / (1024 ** 3) if b > 0 else None
    except Exception:
        return None


def resolve_lane_count(explicit, tac):
    """How many replica lanes to use. Explicit --lanes wins; else auto-size to the host. Only TAC
    (a configured host reset) uses lanes; everything else is 1. CPU-primary, RAM-capped by the
    Docker VM, hard-ceilinged; floor 1 (serial, identical to today)."""
    if explicit and explicit > 0:
        return explicit
    if not tac:
        return 1
    cpu = os.cpu_count() or 1
    cpu_lanes = max(1, cpu // _CPU_PER_LANE)
    vm_gb = _docker_vm_gb()
    ram_lanes = int((vm_gb - _RESERVE_GB) // _PER_ARM_GB) if vm_gb else cpu_lanes
    n = max(1, min(cpu_lanes, ram_lanes if ram_lanes > 0 else 1, _HARD_CAP))
    logger.info("resolve_lane_count: cpu=%d (cpu_lanes=%d) vm=%.1fGiB (ram_lanes=%s) cap=%d -> %d lanes",
                cpu, cpu_lanes, vm_gb or -1, ram_lanes if vm_gb else "n/a", _HARD_CAP, n)
    return n


def main():
    ap = argparse.ArgumentParser(description="Cold-only task calibration (no pairs, no evolved input).")
    ap.add_argument("--group", required=True, help="Domain dir or bare group name.")
    ap.add_argument("--model", required=True)
    ap.add_argument("--meta-model", default=None,
                    help="Model for enabled meta passes (defaults to --model).")
    ap.add_argument("--config", default="memory", choices=sorted(_CONFIG_FLAGS),
                    help="Tool surface for the (empty) store. Match the evolved arm you will later "
                         "compare against, so store CONTENTS are the only difference. Default memory.")
    ap.add_argument("--only", default="",
                    help="Comma-separated task ids to run. Default: every task in the group's "
                         "tasks.json.")
    ap.add_argument("--replicates", type=int, default=3,
                    help="Cold replicates per task (default 3). Each gets its own r<i> subdir.")
    ap.add_argument("--cache-dir", default=".safeevo_tasks_cache",
                    help="Cache ROOT for cold calibration runs (default .safeevo_tasks_cache, "
                         "separate from .safeevo_cache which run_pairs.py owns).")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--port", type=int, default=5800)
    ap.add_argument("--sandbox-mode", default="docker", choices=["docker", "mock"])
    ap.add_argument("--docker-image", default="safeevo-devops")
    ap.add_argument("--docker-memory", default="")
    ap.add_argument("--model-short", default="")
    ap.add_argument("--max-steps-per-task", type=int, default=0)
    ap.add_argument("--enable-planning", action="store_true",
                    help="Give the agent the planning family (off by default for cold calibration).")
    ap.add_argument("--judge", default="")
    ap.add_argument("--arm-timeout", type=int, default=0, help="Per-run wall-clock cap (s); 0 = none.")
    ap.add_argument("--timestamp", default="")
    ap.add_argument(
        "--study-phase",
        default="exploratory",
        choices=("exploratory", "pilot"),
        help="Tag the batch's analysis role. Official headroom inputs must use pilot.",
    )
    ap.add_argument(
        "--study-id",
        default="",
        help="Predeclared study identifier. Required when --study-phase=pilot.",
    )
    ap.add_argument(
        "--freeze-id",
        default="",
        help="Frozen bank identifier. Required when --study-phase=pilot.",
    )
    # External-service flags (TAC group), forwarded verbatim to every run.
    ap.add_argument("--service-host-alias", default="")
    ap.add_argument("--service-env", default="")
    ap.add_argument("--service-reset-cmd", default="")
    ap.add_argument("--service-host-reset-cmd", default="",
                    help="Host-side byte-complete service reset (TAC). Forwarded verbatim to every "
                         "run.py, which runs it on the host between arms. See run.py for details.")
    ap.add_argument("--service-reset-strict", action="store_true",
                    help="Fail closed on reset failure (TAC, Fix B): forwarded to run.py so a "
                         "non-zero reset fails the arm instead of scoring dirty. See run.py.")
    ap.add_argument("--service-network", default="")
    ap.add_argument("--lanes", type=int, default=0,
                    help="TAC replica-lane parallelism. Number of isolated service-stack replicas to "
                         "spread concurrent arms across (each arm gets its own lane, so the GLOBAL "
                         "byte-restore can't corrupt peers). 0 (default) = auto-size to the host "
                         "(resolve_lane_count: CPU-primary, RAM-capped via the Docker VM, hard ceiling); "
                         "1 = serial (identical to today). Bring the lanes up first with "
                         "`python SafeEvoBench/tac/ops/lane_manager.py up --lanes N`. Only meaningful "
                         "when --service-host-reset-cmd is set (TAC); ignored otherwise.")
    args = ap.parse_args()
    if args.study_phase == "pilot" and (not args.study_id or not args.freeze_id):
        ap.error("--study-phase=pilot requires --study-id and --freeze-id")

    # --- TAC concurrency ↔ lanes (Fix C + replica lanes). A configured host reset means arms act on
    #     a SHARED stack and the reset is GLOBAL, so N concurrent arms need N isolated replica lanes or
    #     they corrupt each other. Resolve the lane count (explicit or auto-sized to the host), then
    #     require lanes >= concurrency and clamp. lanes==1 is the serial path (identical to today);
    #     non-TAC ignores lanes entirely.
    is_tac = bool(args.service_host_reset_cmd)
    lane_count = resolve_lane_count(args.lanes, is_tac)
    if is_tac and args.concurrency > lane_count:
        if args.lanes > 0:
            sys.exit(
                f"--concurrency {args.concurrency} exceeds --lanes {lane_count}: each concurrent TAC "
                f"arm needs its own replica lane (the byte-restore reset is GLOBAL per lane). Bring up "
                f"{args.concurrency} lanes first:\n"
                f"  python SafeEvoBench/tac/ops/lane_manager.py up --lanes {args.concurrency}\n"
                f"or lower --concurrency to {lane_count}."
            )
        # auto-sized: clamp concurrency down to the host's safe lane count rather than erroring.
        logger.warning("Auto-sized to %d lane(s) for this host; clamping --concurrency %d -> %d. "
                       "Bring up the lanes: python SafeEvoBench/tac/ops/lane_manager.py up --lanes %d",
                       lane_count, args.concurrency, lane_count, lane_count)
        args.concurrency = lane_count

    group_dir = _resolve_group_dir(args.group)
    tasks = json.load(open(group_dir / "tasks.json")).get("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    if args.only.strip():
        want = [t.strip() for t in args.only.split(",") if t.strip()]
        missing = [t for t in want if t not in by_id]
        if missing:
            sys.exit(f"--only names task id(s) not in {group_dir}/tasks.json: {missing}")
        task_ids = want
    else:
        task_ids = [t["id"] for t in tasks]
    if not task_ids:
        sys.exit(f"no tasks to run in {group_dir}/tasks.json")

    ts = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    model_short = (args.model_short or
                   (args.model.split(".")[-1].split("-v")[0][:25] if "." in args.model
                    else args.model[:25]))
    batch_dir = Path(args.cache_dir) / f"{group_dir.name}_{model_short}_{args.config}_{ts}"
    batch_dir.mkdir(parents=True, exist_ok=True)

    reps = max(1, args.replicates)
    # One run_name per (task, replicate). reps==1 → flat "<task>"; reps>1 → "<task>/r<i>".
    jobs = {}
    for tid in task_ids:
        for i in range(reps):
            jobs[tid if reps == 1 else f"{tid}/r{i}"] = tid

    concurrency = max(1, args.concurrency)
    logger.info("Cold calibration: %d task(s) x %d replicate(s) = %d run(s), config=%s, model=%s",
                len(task_ids), reps, len(jobs), args.config, model_short)
    logger.info("  batch dir: %s", batch_dir)

    ports = queue.Queue()
    for k in range(concurrency):
        ports.put(args.port + k)

    # --- Replica-lane pool (TAC parallelism). One lane per concurrency slot, checked out ALONGSIDE
    #     the port, so each concurrent arm acts on — and resets — its OWN service stack. Built only
    #     when a host reset is configured AND we're actually running >1 lane; otherwise None, and the
    #     arm inherits the parent env unchanged (serial single-stack / devops / fintech). Mirrors
    #     run_pairs.py's ownCloud user pool, generalized from a (user,pass) tuple to a full lane. ---
    lanes_q = None
    if is_tac and lane_count > 1:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "SafeEvoBench" / "tac" / "ops"))
        import lane_manager  # noqa: E402
        pool = lane_manager.lanes(lane_count)
        lanes_q = queue.Queue()
        for lane in pool[:concurrency]:
            lanes_q.put(lane)
        logger.info("  replica lanes: %d (%s) — ensure they are up: "
                    "python SafeEvoBench/tac/ops/lane_manager.py up --lanes %d",
                    concurrency, ", ".join(l.name for l in pool[:concurrency]), concurrency)

    run_dirs = {}

    def _worker(run_name, task_id):
        port = ports.get()
        lane = lanes_q.get() if lanes_q is not None else None
        try:
            d = _run_one(args, batch_dir, run_name, task_id, port, lane=lane)
        finally:
            ports.put(port)
            if lanes_q is not None:
                lanes_q.put(lane)
        run_dirs[run_name] = d
        return run_name

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(_worker, name, tid) for name, tid in jobs.items()]
        done = 0
        for f in as_completed(futs):
            done += 1
            logger.info("  [%d/%d] finished %s", done, len(futs), f.result())

    # --- Assemble per-task cold scores over replicates. ---
    def _dirs_for(tid):
        if reps == 1:
            d = run_dirs.get(tid)
            return [d] if d is not None else []
        return [d for i in range(reps) if (d := run_dirs.get(f"{tid}/r{i}")) is not None]

    results = []
    for tid in task_ids:
        dirs = _dirs_for(tid)
        scored = [_task_scores(d, tid) for d in dirs]
        us = [u for u, _ in scored]
        ss = [s for _, s in scored]
        mu, sdu = _mean_sd(us)
        ms, sds = _mean_sd(ss)
        t = by_id[tid]
        rec = {
            "task_id": tid,
            "safety_label": t.get("safety_label"),
            "risk_category": t.get("risk_category"),
            "harm_locus": t.get("harm_locus"),
            "n": len([s for s in ss if s is not None]),
            "utility": {"mean": mu, "sd": sdu, "runs": us},
            "safety": {"mean": ms, "sd": sds, "runs": ss},
        }
        results.append(rec)
        logger.info("  %-32s util=%s  safety=%s  (n=%d)", tid,
                    f"{mu:.3f}" if mu is not None else "n/a",
                    f"{ms:.3f}" if ms is not None else "n/a", rec["n"])

    out = batch_dir / "collective_results.json"
    out.write_text(json.dumps({
        "schema_version": 1,
        "study_phase": args.study_phase,
        "study_id": args.study_id or f"exploratory-{ts}",
        "freeze_id": args.freeze_id or "unfrozen",
        "batch_id": batch_dir.name,
        "mode": "cold_only",
        "group": args.group, "model": args.model, "config": args.config,
        "meta_model": args.meta_model or args.model,
        "timestamp": ts, "replicates": reps, "batch_dir": str(batch_dir),
        "reported_axes": {"utility": "higher is better",
                          "safety": "higher is better; 1.0 = no hazard (safety = 1 - rubric harm)"},
        "n_tasks": len(results), "tasks": results,
    }, indent=2) + "\n")
    logger.info("Wrote %s (%d tasks)", out, len(results))


if __name__ == "__main__":
    main()
