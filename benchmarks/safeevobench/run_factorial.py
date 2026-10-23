#!/usr/bin/env python3
"""SafeEvoBench factorial pair-runner — checkpoint-shared 2x2 (workspace x store).

For each transfer PAIR X->Y we want the full 2x2 factorial over the two channels by which the
source can influence the target:

                        store EMPTY        store POPULATED (X's store)
    workspace PRISTINE  cold               store_only
    workspace MUTATED   workspace_only     natural

Naively that is cold + 3 arms that each re-run the whole X->Y sequence, so X is executed 3x.
This runner instead executes each PRIMITIVE once and fans the target out over the four starting
conditions:

  * BaseRun(T)      — task T alone, clean image + empty store. Serves DOUBLE duty: it is the
                      `cold` arm for every pair whose target is T, AND (via --commit-image +
                      a store stash) the checkpoint for every pair whose single source is T.
  * PrefixRun(X..)  — a multi-source sequence run once -> checkpoint (image + store stash).
  * FanoutRun(Y)    — task Y alone, started from a checkpoint's image and/or seeded store:
        store_only     = base image           + seed store = ckpt(X).store   (workspace reset)
        natural        = image = ckpt(X)       + seed store = ckpt(X).store
        workspace_only = image = ckpt(X)       + empty store

Checkpoints are CONTENT-ADDRESSED by (model, config, source_seq, replicate) — NOT by pair id —
so pairs that share a source reuse ONE checkpoint (a big saving; documented correlation: within
one replicate, pairs sharing a source share an X realization, so treat them as non-independent
within a replicate; across replicates they are independent).

REPORTED deltas (both are the EVOLUTION-STORE effect, at a fixed workspace level):
  dstore_clean   = store_only - cold        (store effect, workspace reset/pristine in both)
  dstore_carried = natural   - workspace_only (store effect, same mutated workspace in both)
  interaction    = dstore_carried - dstore_clean  (how workspace carryover modulates the store)

--arms selects which contrast to run:
  full            (default) cold + store_only + natural + workspace_only  -> both deltas
  workspace-reset           cold + store_only                            -> dstore_clean only
  store-reset               natural + workspace_only                      -> dstore_carried only

Usage:
    python benchmarks/safeevobench/run_factorial.py --group devops_v2 \
        --model us.anthropic.claude-sonnet-4-6 --judge us.anthropic.claude-sonnet-4-6 \
        --config memory --docker-image safeevo-devops-v2 \
        --arms full --replicates 5 --concurrency 8 --port 5060 --cache-dir .safeevo_cache_v2
"""

import argparse
import hashlib
import json
import logging
import queue
import subprocess
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.safeevobench.run import _resolve_group_dir  # noqa: E402
from benchmarks.safeevobench.run_pairs import (  # noqa: E402  (reuse the canonical helpers)
    _CONFIG_FLAGS, load_pairs, preflight_bedrock, _target_scores, _mean_sd,
    source_evolution, target_reuse, causal_evidence,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("safeevo-factorial")

# Which arms each --arms mode runs. cold is implied by any contrast that needs it.
_ARM_SETS = {
    "full": ["cold", "store_only", "natural", "workspace_only"],
    "workspace-reset": ["cold", "store_only"],
    "store-reset": ["natural", "workspace_only"],
}


def _seq(sources):
    return sources if isinstance(sources, list) else [sources]


def _ckpt_hash(model, config, source_seq, rep):
    """Content address for a checkpoint: a source sequence run under (model, config, replicate).
    Shared across every pair with the same source(s) — the key saving. Short hex tag."""
    raw = json.dumps([model, config, list(source_seq), rep], sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# Subprocess wrapper: one run.py invocation = one unit (base / prefix / fanout).
# --------------------------------------------------------------------------- #
def _run_unit(args, batch_dir, run_name, task_list, config, port, *,
              reset_workspace=False, commit_image=None, seed_store=None, docker_image=None):
    """Launch one run.py subprocess. Returns the run-dir Path on success, else None.
    `docker_image` overrides args.docker_image (fan-out arms start from a checkpoint image).
    `commit_image` / `seed_store` thread the new run.py hooks. Mirrors run_pairs._run_arm's
    container/timeout cleanup so a wedged unit can't stall the pool."""
    cmd = [
        sys.executable, str(Path(__file__).with_name("run.py")),
        "--group", args.group,
        "--model", args.model,
        "--run-name", run_name,
        "--cache-dir", str(batch_dir),
        "--sandbox-mode", args.sandbox_mode,
        "--task-list", ",".join(task_list),
        # Forward planning explicitly so every arm (base/prefix/fanout) matches the
        # factorial-level setting. Missing legacy callers inherit the opt-in default.
        "--enable-planning" if getattr(args, "enable_planning", False) else "--no-enable-planning",
        "--evaluate",
    ]
    if getattr(args, "max_steps", None):
        cmd += ["--max-steps-per-task", str(args.max_steps)]
    if reset_workspace:
        cmd += ["--reset-workspace"]
    if commit_image:
        cmd += ["--commit-image", commit_image]
    if seed_store:
        cmd += ["--seed-store", str(seed_store)]
    if args.judge:
        cmd += ["--judge", args.judge]
    if args.meta_model:
        cmd += ["--meta-model", args.meta_model]
    if args.sandbox_mode == "docker":
        cmd += ["--docker-image", docker_image or args.docker_image, "--port", str(port)]
        if args.docker_memory:
            cmd += ["--docker-memory", args.docker_memory]
    cmd += _CONFIG_FLAGS[config]
    logger.info("  unit start: %s  [%s]  port=%s  tasks=%s%s%s", run_name, config, port, task_list,
                "  +commit" if commit_image else "", "  +seed" if seed_store else "")
    timeout = args.arm_timeout if args.arm_timeout > 0 else None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("  unit TIMEOUT (>%ss): %s — killing + cleaning its container", timeout, run_name)
        if args.sandbox_mode == "docker":
            subprocess.run(["bash", "-c",
                            f"docker ps -aq --filter publish={port} | xargs -r docker rm -f"],
                           capture_output=True)
        return None
    if result.returncode != 0:
        tail = "\n".join((result.stderr or "").strip().splitlines()[-3:])
        logger.error("  unit FAILED (exit %d): %s\n    %s", result.returncode, run_name, tail)
        if args.sandbox_mode == "docker":
            subprocess.run(["bash", "-c",
                            f"docker ps -aq --filter publish={port} | xargs -r docker rm -f"],
                           capture_output=True)
        return None
    logger.info("  unit done:  %s", run_name)
    return Path(batch_dir) / run_name


def _stash_store(run_dir, stash_dir):
    """Copy a completed unit's evolution artifacts into stash_dir (the checkpoint's store).
    Returns the stash_dir. Includes the memory/skills/subagents JSONs AND evolved_prompt.txt (the
    evolve family's rewritten base prompt), so `--seed-store` restores the FULL disposition —
    stores + evolved prompt. Only files that exist are copied; an evolution-free run yields an
    empty stash (which seeds as an empty store — harmless)."""
    import shutil
    stash_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("memory.json", "skills.json", "subagents.json", "evolved_prompt.txt"):
        src = Path(run_dir) / fname
        if src.exists():
            shutil.copy2(src, stash_dir / fname)
    return stash_dir


def _rmi(tag):
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


# --------------------------------------------------------------------------- #
# Planner: decompose all pairs into the minimal set of primitive units.
# --------------------------------------------------------------------------- #
def plan_units(pairs, arms, reps):
    """Return (checkpoints, base_targets, fanouts).

    checkpoints: {ckpt_hash: {"source_seq":[...], "rep":i, "need_image":bool, "need_store":bool,
                              "is_single_base": bool}}  — one build per (source_seq, rep).
    base_targets: {(target, rep)} that need a clean solo run for the `cold` arm. NOTE a single
                  source that is also the checkpoint for its pair is built as a BaseRun and, when
                  that source == some target, the SAME base unit serves cold(target) too — we
                  unify by keying base runs on (task, rep) and letting a base run double as both a
                  cold score and a single-source checkpoint (commit+stash).
    fanouts: list of {pair_id, quadrant, target, ckpt_hash, arm, rep} for the non-cold arms.
    """
    want = set(_ARM_SETS[arms])
    need_ckpt = bool(want & {"store_only", "natural", "workspace_only"})
    # Which checkpoint capabilities the requested arms need:
    need_image = bool(want & {"natural", "workspace_only"})   # start Y from X's workspace image
    need_store = bool(want & {"store_only", "natural"})       # seed Y with X's store

    checkpoints = {}
    base_runs = {}   # (task, rep) -> {"is_ckpt_for": set(ckpt_hash)}  (a base run may double as ckpt)
    fanouts = []

    for rep in range(reps):
        for p in pairs:
            pid = p["id"]
            srcs = _seq(p["source"])
            tgt = p["target"] if isinstance(p["target"], str) else _seq(p["target"])[0]
            # cold(target): a clean solo run of the target (deduped by (target, rep)).
            if "cold" in want:
                base_runs.setdefault((tgt, rep), {"is_ckpt_for": set()})
            if not need_ckpt:
                continue
            ch = _ckpt_hash(p.get("model_key", ""), p.get("config_key", ""), srcs, rep)
            # register the checkpoint (build once, shared across pairs with same source_seq)
            ck = checkpoints.setdefault(ch, {
                "source_seq": list(srcs), "rep": rep,
                "need_image": need_image, "need_store": need_store,
                "single": len(srcs) == 1,
            })
            # a single-source checkpoint IS a base run of that source (unify with cold if same task)
            if len(srcs) == 1:
                br = base_runs.setdefault((srcs[0], rep), {"is_ckpt_for": set()})
                br["is_ckpt_for"].add(ch)
            for arm in want:
                if arm == "cold":
                    continue
                fanouts.append({"pair_id": pid, "quadrant": p.get("quadrant"), "target": tgt,
                                "ckpt_hash": ch, "arm": arm, "rep": rep})
    return checkpoints, base_runs, fanouts


def main():
    ap = argparse.ArgumentParser(description="SafeEvoBench factorial runner (checkpoint-shared 2x2).")
    ap.add_argument("--group", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--meta-model", default=None,
                    help="Model for enabled meta passes (defaults to --model).")
    ap.add_argument("--config", default="memory", choices=list(_CONFIG_FLAGS))
    ap.add_argument("--judge", default=None)
    ap.add_argument("--pairs", default=None, help="Comma-separated pair ids (default: all).")
    ap.add_argument("--arms", default="full", choices=list(_ARM_SETS),
                    help="Which contrast to run: full (both store deltas), workspace-reset "
                         "(dstore_clean only), store-reset (dstore_carried only).")
    ap.add_argument("--cache-dir", default=".safeevo_cache_v2")
    ap.add_argument("--sandbox-mode", default="docker", choices=["docker", "mock"])
    ap.add_argument("--docker-image", default="safeevo-devops-v2")
    ap.add_argument("--docker-memory", default="2g")
    ap.add_argument("--enable-planning", action=argparse.BooleanOptionalAction, default=False,
                    help="Give the agent the planning family (create_task_plan + planning gate). "
                         "Off by default; pass --enable-planning to opt in across ALL "
                         "arms (base, prefix, and fan-out runs are forwarded the same setting).")
    ap.add_argument("--replicates", type=int, default=1)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--port", type=int, default=5060)
    ap.add_argument("--arm-timeout", type=int, default=1800)
    ap.add_argument("--max-steps", type=int, default=None,
                    help="Cap steps per task (forwarded to run.py --max-steps-per-task). Mainly "
                         "for fast smoke/mock runs; unset uses run.py's default.")
    ap.add_argument("--timestamp", default=None)
    ap.add_argument("--no-preflight", action="store_true")
    ap.add_argument("--keep-checkpoints", action="store_true",
                    help="Do not delete committed checkpoint images / store stashes after the run "
                         "(debug; default off — they are removed once all consumers finish).")
    args = ap.parse_args()
    if args.replicates < 1:
        ap.error("--replicates must be >= 1")

    if args.sandbox_mode == "docker" and not args.no_preflight:
        preflight_bedrock([args.model, args.judge, args.meta_model])

    group_dir = _resolve_group_dir(args.group)
    pairs = load_pairs(group_dir, args.pairs.split(",") if args.pairs else None)
    if not pairs:
        logger.error("No pairs matched.")
        sys.exit(1)
    # stamp model/config into each pair so the planner's ckpt hash is model/config-scoped
    for p in pairs:
        p["model_key"], p["config_key"] = args.model, args.config

    ts = args.timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    model_short = args.model.split(".")[-1].split("-v")[0][:25] if "." in args.model else args.model[:25]
    batch_dir = Path(args.cache_dir) / f"seb_{model_short}_{args.config}_{ts}"
    (batch_dir / "units").mkdir(parents=True, exist_ok=True)
    (batch_dir / "checkpoints").mkdir(parents=True, exist_ok=True)

    checkpoints, base_runs, fanouts = plan_units(pairs, args.arms, args.replicates)
    logger.info("Factorial plan: arms=%s reps=%d | %d base runs, %d checkpoints, %d fan-out runs",
                args.arms, args.replicates, len(base_runs), len(checkpoints), len(fanouts))
    logger.info("  batch dir: %s", batch_dir)

    concurrency = max(1, args.concurrency)
    ports = queue.Queue()
    for k in range(concurrency):
        ports.put(args.port + k)
    lock = threading.Lock()

    # Shared state populated by the executor.
    base_dirs = {}     # (task, rep) -> run_dir | None
    base_scores = {}   # (task, rep) -> (util, harm)
    prefix_dirs = {}   # ckpt_hash -> run_dir | None   (multi-source source-sequence runs)
    ckpt_ready = {}    # ckpt_hash -> {"image": tag|None, "store": stash_dir|None} | None on failure

    def _worker_base(task, rep, ckpt_hashes):
        """Run BaseRun(task, rep). Serves cold(task); if it is a single-source checkpoint for one
        or more ckpt_hashes, also commit its image + stash its store for those checkpoints."""
        port = ports.get()
        try:
            run_name = f"units/base_{task}__r{rep}"
            commit_tag = None
            # any of the checkpoints this base backs need an image?
            need_image = any(checkpoints[h]["need_image"] for h in ckpt_hashes)
            need_store = any(checkpoints[h]["need_store"] for h in ckpt_hashes)
            if ckpt_hashes and need_image and args.sandbox_mode == "docker":
                commit_tag = f"ckpt_{sorted(ckpt_hashes)[0]}"  # one image; aliased below if shared
            d = _run_unit(args, batch_dir, run_name, [task], args.config, port,
                          commit_image=commit_tag)
            with lock:
                base_dirs[(task, rep)] = d
                base_scores[(task, rep)] = _target_scores(d, task) if d else (None, None)
                # publish checkpoint artifacts for every ckpt this base backs
                for h in ckpt_hashes:
                    if d is None:
                        ckpt_ready[h] = None
                        continue
                    store = None
                    if checkpoints[h]["need_store"]:
                        store = _stash_store(d, batch_dir / "checkpoints" / f"ckpt_{h}" / "store")
                    img = None
                    if checkpoints[h]["need_image"] and commit_tag:
                        img = f"ckpt_{h}"
                        if img != commit_tag:  # alias the single committed image to this hash tag
                            subprocess.run(["docker", "tag", commit_tag, img], capture_output=True)
                    ckpt_ready[h] = {"image": img, "store": store}
        finally:
            ports.put(port)
        return ("base", task, rep)

    def _worker_prefix(ch):
        """Run PrefixRun for a multi-source checkpoint: execute the source sequence, commit image
        + stash store. (Single-source checkpoints are produced by _worker_base instead.)"""
        port = ports.get()
        c = checkpoints[ch]
        try:
            run_name = f"units/prefix_{ch}__r{c['rep']}"
            commit_tag = f"ckpt_{ch}" if (c["need_image"] and args.sandbox_mode == "docker") else None
            d = _run_unit(args, batch_dir, run_name, c["source_seq"], args.config, port,
                          commit_image=commit_tag)
            with lock:
                prefix_dirs[ch] = d
                if d is None:
                    ckpt_ready[ch] = None
                else:
                    store = _stash_store(d, batch_dir / "checkpoints" / f"ckpt_{ch}" / "store") \
                        if c["need_store"] else None
                    ckpt_ready[ch] = {"image": (f"ckpt_{ch}" if commit_tag else None), "store": store}
        finally:
            ports.put(port)
        return ("prefix", ch)

    def _worker_fanout(fo):
        """Run one fan-out Y-run from its checkpoint, per the arm's (image, store) recipe."""
        port = ports.get()
        try:
            ck = ckpt_ready.get(fo["ckpt_hash"])
            if ck is None:
                with lock:
                    fo["dir"] = None
                    fo["scores"] = (None, None)
                return ("fanout", fo["pair_id"], fo["arm"])
            arm = fo["arm"]
            image = ck["image"] if arm in ("natural", "workspace_only") else args.docker_image
            seed = ck["store"] if arm in ("store_only", "natural") else None
            # store_only starts from a PRISTINE workspace (base image) but seeded store;
            # natural starts from the checkpoint image + seeded store;
            # workspace_only starts from the checkpoint image + EMPTY store.
            run_name = f"units/fanout_{fo['pair_id']}_{arm}__r{fo['rep']}"
            d = _run_unit(args, batch_dir, run_name, [fo["target"]], args.config, port,
                          seed_store=seed, docker_image=image)
            with lock:
                fo["dir"] = d
                fo["scores"] = _target_scores(d, fo["target"]) if d else (None, None)
        finally:
            ports.put(port)
        return ("fanout", fo["pair_id"], fo["arm"])

    # --- Level 0: base runs + multi-source prefixes (build checkpoints + cold scores) ---
    single_ckpt_hashes = {h for h, c in checkpoints.items() if c["single"]}
    multi_ckpts = [h for h, c in checkpoints.items() if not c["single"]]
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = []
        for (task, rep), meta in base_runs.items():
            futs.append(pool.submit(_worker_base, task, rep, sorted(meta["is_ckpt_for"])))
        for ch in multi_ckpts:
            futs.append(pool.submit(_worker_prefix, ch))
        done = 0
        for f in as_completed(futs):
            done += 1
            logger.info("  [L0 %d/%d] %s", done, len(futs), f.result())

    # --- Level 1: fan-out Y-runs (each starts as soon as its checkpoint is ready; here all L0
    #     finished, so ckpt_ready is fully populated). ---
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futs = [pool.submit(_worker_fanout, fo) for fo in fanouts]
        done = 0
        for f in as_completed(futs):
            done += 1
            if done % 10 == 0 or done == len(futs):
                logger.info("  [L1 %d/%d fan-out runs]", done, len(futs))

    # --- Level 2: JOIN -> pairs.json (+ units.json manifest) ---
    _join_and_write(args, batch_dir, pairs, base_dirs, base_scores, prefix_dirs, fanouts,
                    ts, model_short)

    # --- checkpoint cleanup (ref-counted implicitly: all consumers have finished) ---
    if not args.keep_checkpoints and args.sandbox_mode == "docker":
        for h in checkpoints:
            _rmi(f"ckpt_{h}")
        # single-source base commits used the first-hash tag; those are the same images (aliased),
        # already removed above by their ckpt_<h> tags.
    logger.info("Done. Analyze with: python benchmarks/safeevobench/transfer_factorial.py %s",
                batch_dir)


def _source_unit_dir(args, batch_dir, base_dirs, prefix_dirs, p, srcs, rep=0):
    """The unit dir in which this pair's SOURCE task(s) actually executed, or None.

    Mirrors plan_units' dedup: a single source is run as BaseRun(src, rep) (which also backs
    the checkpoint); a source SEQUENCE is run as PrefixRun -> units/prefix_{ckpt}__r{rep}.
    Falls back to the on-disk path when the in-memory map is missing the entry (e.g. a resumed
    or externally assembled batch)."""
    if len(srcs) == 1:
        d = base_dirs.get((srcs[0], rep))
        if d:
            return d
        d = Path(batch_dir) / "units" / f"base_{srcs[0]}__r{rep}"
        return d if d.exists() else None
    ch = _ckpt_hash(p.get("model_key", ""), p.get("config_key", ""), srcs, rep)
    d = prefix_dirs.get(ch)
    if d:
        return d
    d = Path(batch_dir) / "units" / f"prefix_{ch}__r{rep}"
    return d if d.exists() else None


def _join_and_write(args, batch_dir, pairs, base_dirs, base_scores, prefix_dirs, fanouts,
                    ts, model_short):
    """Assemble per-pair 2x2 rows from the deduped units and write pairs.json + units.json.
    Reports the two store-effect deltas + interaction. reps folded per (pair, arm)."""
    reps = args.replicates
    # index fan-out results: (pair_id, arm) -> [(u,h) per rep]
    fo_by = defaultdict(list)
    fo_dir0 = {}   # (pair_id, arm) -> first run_dir (for provenance/reuse)
    for fo in fanouts:
        fo_by[(fo["pair_id"], fo["arm"])].append(fo.get("scores", (None, None)))
        fo_dir0.setdefault((fo["pair_id"], fo["arm"]), fo.get("dir"))

    def _axis(vals, i):
        return _mean_sd([v[i] for v in vals]) if vals else (None, None)

    def _arm_block(scores_list):
        """Per-arm block on the REPORTED axes: utility and SAFETY, both higher-is-better.

        `_target_scores` returns the rubric's raw harm (higher = worse); it is converted here, once,
        at the reporting boundary: safety = 1 - harm. This runner previously emitted raw `harm`
        while run_pairs.py emitted `safety`, so the same underlying number carried opposite signs in
        two summaries that a reader would naturally compare. Unifying on safety means a negative
        delta is a degradation on either axis, in either runner."""
        (mu, sdu), (mh, sdh) = _axis(scores_list, 0), _axis(scores_list, 1)
        ms = (1.0 - mh) if mh is not None else None
        safeties = [(1.0 - v[1]) if v[1] is not None else None for v in scores_list]
        if reps == 1:
            return {"utility": mu, "safety": ms}, mu, ms
        return ({"utility": {"mean": mu, "sd": sdu, "runs": [v[0] for v in scores_list]},
                 "safety": {"mean": ms, "sd": sdh, "runs": safeties}}, mu, ms)

    results = []
    for p in pairs:
        pid = p["id"]
        tgt = p["target"] if isinstance(p["target"], str) else _seq(p["target"])[0]
        srcs = _seq(p["source"])
        # cold from the deduped base runs across reps
        cold_scores = [base_scores.get((tgt, r), (None, None)) for r in range(reps)]
        cold_block, cu, ch = _arm_block(cold_scores)
        rec = {"pair_id": pid, "quadrant": p.get("quadrant"), "sources": srcs, "target": tgt,
               "cold": cold_block}
        arm_means = {"cold": (cu, ch)}
        for arm in ("store_only", "natural", "workspace_only"):
            sl = fo_by.get((pid, arm))
            if not sl:
                continue
            block, mu, mh = _arm_block(sl)
            rec[arm] = block
            arm_means[arm] = (mu, mh)

        def _d(a, b):
            return (a - b) if (a is not None and b is not None) else None
        cu_, cs_ = arm_means.get("cold", (None, None))
        so_u, so_s = arm_means.get("store_only", (None, None))
        na_u, na_s = arm_means.get("natural", (None, None))
        wo_u, wo_s = arm_means.get("workspace_only", (None, None))
        # The two REPORTED store-effect deltas + the interaction, on utility and SAFETY (both
        # higher-is-better, so a negative delta is a degradation on either axis).
        rec["delta_store_clean"] = {"utility": _d(so_u, cu_), "safety": _d(so_s, cs_)}
        rec["delta_store_carried"] = {"utility": _d(na_u, wo_u), "safety": _d(na_s, wo_s)}
        rec["delta_interaction"] = {
            "utility": _d(rec["delta_store_carried"]["utility"], rec["delta_store_clean"]["utility"]),
            "safety": _d(rec["delta_store_carried"]["safety"], rec["delta_store_clean"]["safety"]),
        }
        # Q1 (evolved-in-source) is a property of the SOURCE run, which in this layout is a
        # separate unit: the base run of a single source, or the prefix run of a sequence. The
        # fan-out (target) dirs never contain source-task artifacts, so reading Q1 off them
        # silently reports zero for every pair — notably prompt: 0 for the whole evolve family.
        src_dir = _source_unit_dir(args, batch_dir, base_dirs, prefix_dirs, p, srcs, rep=0)
        rec["source_evolution"] = source_evolution(src_dir, srcs)
        # Q2 (reused-in-target) is a property of the TARGET arm and stays on the fan-out dir.
        tgt_dir = fo_dir0.get((pid, "natural")) or fo_dir0.get((pid, "store_only"))
        rec["target_reuse"] = target_reuse(tgt_dir, srcs, tgt)
        # Q2b: pulled-and-used vs pulled-and-dismissed. target_reuse counts pulls only, and a
        # dismissed pull scored as transfer is a live overclaim (see run_pairs.causal_evidence).
        rec["causal_evidence"] = causal_evidence(tgt_dir, srcs, tgt)
        rec["units"] = {
            "cold": [str(base_dirs.get((tgt, r))) for r in range(reps) if base_dirs.get((tgt, r))],
            **({"source": str(src_dir)} if src_dir else {}),
            **{arm: str(fo_dir0.get((pid, arm))) for arm in ("store_only", "natural", "workspace_only")
               if fo_dir0.get((pid, arm))},
        }
        results.append(rec)

    (batch_dir / "pairs.json").write_text(json.dumps({
        "group": args.group, "model": args.model, "config": args.config, "arms": args.arms,
        "meta_model": getattr(args, "meta_model", None) or args.model,
        "factorial": True, "timestamp": ts, "replicates": reps, "batch_dir": str(batch_dir),
        "reported_axes": {"utility": "higher is better",
                          "safety": "higher is better; 1.0 = no hazard (safety = 1 - rubric harm)"},
        "n_pairs": len(results), "pairs": results,
    }, indent=2) + "\n")
    logger.info("Wrote %s (%d pairs)", batch_dir / "pairs.json", len(results))


if __name__ == "__main__":
    main()
