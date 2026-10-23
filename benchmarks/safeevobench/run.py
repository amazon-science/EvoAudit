#!/usr/bin/env python3
"""
Run SafeEvoBench benchmark tasks and produce a summary report with
safety scores, evolution metrics, and tool usage stats.

Usage:
    # Basic run:
    python benchmarks/safeevobench/run.py --group devops \
        --model us.anthropic.claude-sonnet-4-20250514-v1:0

    # With evolution:
    python benchmarks/safeevobench/run.py --group devops \
        --model us.anthropic.claude-sonnet-4-20250514-v1:0 \
        --enable-memory --enable-skills --enable-subagents --enable-evolve

    # Mock sandbox (no Docker, for testing):
    python benchmarks/safeevobench/run.py --group devops \
        --model us.anthropic.claude-sonnet-4-20250514-v1:0 --sandbox-mode mock

    # With evaluation:
    python benchmarks/safeevobench/run.py --group devops \
        --model us.anthropic.claude-sonnet-4-20250514-v1:0 \
        --enable-memory --enable-skills --enable-subagents --enable-evolve --evaluate
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Repo root is two levels up (benchmarks/safeevobench/run.py -> repo root).
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchmarks.safeevobench.adapter import build_agent
from continual_harness.config import (
    EVOLUTION_PROMPT_VARIANTS,
    MEMORY_PROMPT_VARIANTS,
)

# Where SafeEvoBench group data (devops/, with tasks.json + workspace/ +
# evaluation/) lives. Kept as a single constant so the data root is one edit.
_SAFEEVO_DATA_ROOT = Path(__file__).resolve().parents[2] / "SafeEvoBench"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docker sandbox
# ---------------------------------------------------------------------------

class SafeEvoDockerSandbox:
    """Docker sandbox that manages its own container lifecycle.

    `network` (optional) attaches the executor container to an existing Docker network so
    its /workspace/scripts wrappers can reach a persistent service stack by service name.
    When None (the default, used by the DevOps domain) the `docker run` invocation is
    unchanged.
    """

    def __init__(self, image_name: str = "safeevo-devops", port: int = 5055,
                 network: Optional[str] = None, health_timeout: int = 30,
                 host_alias: Optional[str] = None, env_pass: Optional[list] = None,
                 memory: Optional[str] = None, expected_build_digest: Optional[str] = None,
                 service_reset_cmd: Optional[str] = None,
                 service_host_reset_cmd: Optional[str] = None,
                 service_reset_strict: bool = False,
                 scenario_time: Optional[str] = None):
        self.image_name = image_name
        # Optional per-task scenario clock, overriding the image's SCENARIO_TIME default. Tasks
        # whose fixtures are dated outside the image's pinned "now" would otherwise present the
        # agent with future-dated work — a non-hazard reason to distrust the workspace, which
        # confounds the effect being measured. Set via set_scenario_time() before the container is
        # (re)created; None leaves the `docker run` invocation exactly as it was, so the image ENV
        # remains the default for every task that does not declare one.
        self.scenario_time = scenario_time
        # Optional image-verification guard. When a group declares a build_digest (via its
        # tasks.json), the container must report a matching opaque build fingerprint through
        # /health, or the run aborts — so a stale/wrong image can never silently be used. The
        # digest is a neutral hex string (no self-identifying content), so it is not agent-visible
        # as a benchmark tell. None = no check (unchanged for groups that don't declare one).
        self.expected_build_digest = expected_build_digest
        self.port = port
        self.network = network
        self.host_alias = host_alias
        # Names of host env vars to forward into the container (e.g. GITLAB_TOKEN) so the
        # /workspace/scripts wrappers can authenticate. Empty by default (DevOps unchanged).
        self.env_pass = env_pass or []
        self.health_timeout = health_timeout
        # Optional per-container memory cap (docker --memory value, e.g. "2g"). Bounds a
        # single container so it can't starve peers when several run concurrently (pairs).
        # None = no limit (unchanged single-run behavior).
        self.memory = memory
        # Optional command run INSIDE the freshly-started container (via /execute) right after
        # it becomes healthy, at container-start AND on every reset_workspace. For groups whose
        # real state lives in EXTERNAL persistent services (the TAC group: GitLab/ownCloud/
        # RocketChat), recreating the executor container does NOT reset that state — a share/merge
        # from one arm would leak into the next and break arm-equivalence. This command (e.g.
        # `bash /workspace/scripts/service_reset.sh`) undoes what tasks touched, restoring the
        # services to a known baseline. None = no service reset (DevOps/fintech unchanged; their
        # workspace is fully baked into the image, so container recreation is a complete reset).
        self.service_reset_cmd = service_reset_cmd
        # Optional command run on the HOST (not in the container) right after the in-container reset,
        # at container-start AND on every reset_workspace. The in-container reset above can only reach
        # the services over the network via curl wrappers; it CANNOT do byte-complete restores
        # (mongorestore --drop, ownCloud volume swap) which are host-side `docker` operations. This
        # host command (e.g. `bash SafeEvoBench/tac/ops/service_reset_host.sh`) performs those.
        # It runs in the harness's own host shell — the same context that issues `docker run` — so it
        # can exec into the service containers. None = no host reset (DevOps/fintech unchanged; NOT a
        # docker-run flag, so their `docker run` argv is byte-identical whether this is set or not).
        self.service_host_reset_cmd = service_host_reset_cmd
        # Fail-closed switch (Fix B). When True, a non-zero return from EITHER reset command raises
        # instead of only logging, so the arm fails rather than scoring against contaminated state.
        # Default False preserves the historical log-and-continue behaviour for any caller that does
        # not opt in; only the TAC runner sets it (alongside the reset commands). It has no effect
        # when no reset command is configured, so DevOps/fintech are unaffected regardless.
        self.service_reset_strict = service_reset_strict
        self.container_name = f"safeevo-run-{os.getpid()}-{port}"
        self.base_url = f"http://localhost:{port}"
        self._start_container()

    def _free_port(self):
        """Remove ANY container publishing our host port, not just our own name.

        Arms run as separate processes and the container name embeds the pid, so a
        container leaked by a *previous* arm on this port (crash, or teardown lag)
        has a different name and our name-based `docker rm` would miss it — leaving
        the port bound and the next `docker run` failing with 'port is already
        allocated'. Filtering by published port catches those strays too."""
        import subprocess
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        subprocess.run(
            ["bash", "-c",
             f"docker ps -aq --filter publish={self.port} | xargs -r docker rm -f"],
            capture_output=True,
        )

    def _start_container(self):
        import subprocess
        cmd = ["docker", "run", "-d", "--name", self.container_name,
               "-p", f"127.0.0.1:{self.port}:5000"]
        if self.memory:
            cmd += ["--memory", self.memory, "--memory-swap", self.memory]
        # Only inject --network when a private service network is in play; otherwise leave the
        # invocation exactly as it was for the DevOps domain.
        if self.network:
            cmd += ["--network", self.network]
        # TheAgentCompany publishes its services on the host under one hostname
        # (the-agent-company.com:<port>). --add-host <alias>:host-gateway lets the executor
        # container resolve that hostname to the host on both Linux and Docker Desktop, so the
        # /workspace/scripts wrappers reach the real services. Off by default (DevOps unchanged).
        if self.host_alias:
            cmd += ["--add-host", f"{self.host_alias}:host-gateway"]
        # Forward selected host env vars (e.g. GITLAB_TOKEN) into the container so the wrappers
        # can authenticate. Only vars actually set on the host are passed.
        for name in self.env_pass:
            val = os.environ.get(name)
            if val is not None:
                cmd += ["-e", f"{name}={val}"]
        # Per-task scenario clock. `docker run -e` overrides the image's ENV, and the executor
        # disables faketime on an empty value, so a task may either move the clock or turn it off.
        # Only emitted when a task declares one, leaving every other group's invocation unchanged.
        if self.scenario_time is not None:
            cmd += ["-e", f"SCENARIO_TIME={self.scenario_time}"]
        cmd.append(self.image_name)
        # Retry the bind: under the full-suite sweep, Docker can still hold a just-freed
        # port for a moment when the pool hands it to the next arm. On the specific
        # 'port is already allocated' error, clear any occupant and back off, then retry.
        last_err = ""
        for attempt in range(6):
            self._free_port()
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                break
            last_err = result.stderr or ""
            if "already allocated" in last_err or "port is already" in last_err.lower() \
                    or "Bind for" in last_err:
                logger.warning("port %d busy (attempt %d/6), clearing + retrying: %s",
                               self.port, attempt + 1, last_err.strip().splitlines()[-1:] or "")
                time.sleep(2 * (attempt + 1))
                continue
            raise RuntimeError(f"Failed to start container: {last_err}")
        else:
            raise RuntimeError(f"Failed to start container after retries (port {self.port} "
                               f"stayed allocated): {last_err}")
        logger.info("Started container %s on port %d%s%s", self.container_name, self.port,
                    f" (network {self.network})" if self.network else "",
                    f" (host-alias {self.host_alias})" if self.host_alias else "")
        self._wait_for_health(timeout=self.health_timeout)
        # External-service reset (TAC group). Runs on first start AND — because reset_workspace()
        # recreates the container via this same method — on every between-task workspace reset.
        self._run_service_reset()
        # Host-side byte-complete reset (TAC group), AFTER the in-container reset so it has the last
        # word on service state (the in-container reset only owns the in-image logs/control-state
        # files once Fix A lands; the host reset owns the actual service bytes).
        self._run_service_host_reset()

    def _run_service_host_reset(self):
        """Run the domain's host-side byte-complete service reset (TAC group).

        No-op unless a `service_host_reset_cmd` was configured. Unlike _run_service_reset (which
        runs INSIDE the container via /execute and can only curl the services), this runs on the
        HOST via subprocess, so it can `docker exec`/volume-restore the service containers —
        mongorestore --drop of RocketChat's mutable collections and an ownCloud volume swap. That is
        the only way to restore state byte-for-byte rather than surface-by-surface.

        On a non-zero return: in strict mode (Fix B, TAC) this RAISES, so the failure propagates out
        of _start_container and the arm fails rather than scoring against contaminated state; in
        non-strict mode it is logged loudly and execution continues (historical behaviour)."""
        if not self.service_host_reset_cmd:
            return
        import subprocess
        logger.info("Running host-side service reset: %s", self.service_host_reset_cmd)
        result = subprocess.run(self.service_host_reset_cmd, shell=True,
                                capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            msg = (f"HOST SERVICE RESET FAILED (rc={result.returncode}): {self.service_host_reset_cmd}\n"
                   f"  stdout: {(result.stdout or '')[-500:]}\n  stderr: {(result.stderr or '')[-500:]}")
            if self.service_reset_strict:
                raise RuntimeError(msg)
            logger.error(msg)
        else:
            logger.info("Host-side service reset OK")

    def _run_service_reset(self):
        """Run the domain's external-service reset command inside the fresh container.

        No-op unless a `service_reset_cmd` was configured (only the TAC group sets it). The
        command runs via /execute, so it uses the container's wrappers + the forwarded
        service credentials + the host-alias resolution that already reach the live services.
        On a non-zero return: in strict mode (Fix B, TAC) this RAISES so the arm fails rather than
        scoring against control-state files the prior arm left behind; in non-strict mode it is
        logged and execution continues (historical behaviour)."""
        if not self.service_reset_cmd:
            return
        logger.info("Running external-service reset: %s", self.service_reset_cmd)
        result = self.execute(self.service_reset_cmd, timeout=300)
        if result.get("returncode", 0) != 0:
            msg = (f"SERVICE RESET FAILED (rc={result.get('returncode')}): {self.service_reset_cmd}\n"
                   f"  stderr: {(result.get('stderr') or '')[:500]}")
            if self.service_reset_strict:
                raise RuntimeError(msg)
            logger.error(msg)
        else:
            logger.info("External-service reset OK")

    def _wait_for_health(self, timeout: int = 30):
        import json as _json
        import urllib.request
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                req = urllib.request.Request(f"{self.base_url}/health")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        logger.info("Container is healthy")
                        try:
                            payload = _json.loads(resp.read().decode())
                        except Exception:
                            payload = {}
                        self._verify_image_identity(payload)
                        return
            except RuntimeError:
                raise  # image-identity mismatch — abort loudly, do not keep polling
            except Exception:
                pass
            time.sleep(1)
        raise TimeoutError(f"Container did not become healthy within {timeout}s")

    def _verify_image_identity(self, health_payload: dict):
        """Abort if the group expects a specific build_digest and the running container's baked-in
        opaque build fingerprint (echoed by /health as 'build') does not match. Prevents silently
        running against a stale/wrong image that lacks the intended stateful engine."""
        if not self.expected_build_digest:
            return
        got = (health_payload or {}).get("build", "")
        if got != self.expected_build_digest:
            raise RuntimeError(
                f"IMAGE BUILD MISMATCH: group expects build_digest={self.expected_build_digest!r} but "
                f"the running container (image {self.image_name!r}) reports build={got!r}. "
                f"Refusing to run — this is likely a stale/wrong --docker-image. Rebuild the image "
                f"from this group's Dockerfile and pass it via --docker-image."
            )

    def execute(self, command: str, timeout: int = 120) -> Dict[str, Any]:
        import urllib.request, urllib.error
        payload = json.dumps({"command": command}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/execute", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return {"stdout": "", "stderr": e.read().decode("utf-8") if e.fp else str(e), "returncode": -1}
        except urllib.error.URLError as e:
            return {"stdout": "", "stderr": f"Connection error: {e}", "returncode": -1}
        except Exception as e:
            return {"stdout": "", "stderr": str(e), "returncode": -1}
        return {"stdout": result.get("stdout", ""), "stderr": result.get("stderr", ""), "returncode": result.get("returncode", 0)}

    def set_scenario_time(self, scenario_time: Optional[str]) -> bool:
        """Point the scenario clock at `scenario_time` for subsequent tasks.

        Recreates the container ONLY when the value actually changes, since the clock is fixed at
        `docker run` time and cannot be re-pointed in a live container. Returns True if the
        container was recreated. Passing None restores the image's own SCENARIO_TIME default.

        A recreate discards /workspace, which is exactly the pristine-baseline guarantee the cold
        arm already relies on (see reset_workspace) — but it must therefore happen BEFORE a task
        runs, never mid-task. Tasks that declare no scenario_time never trigger it.
        """
        if scenario_time == self.scenario_time:
            return False
        self.scenario_time = scenario_time
        import subprocess
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        self._start_container()
        logger.info("Scenario clock set to %r: recreated container %s",
                    scenario_time or "<image default>", self.container_name)
        return True

    def reset_workspace(self):
        """Recreate the container so /workspace returns to its pristine baked state.

        The workspace is COPY-baked into the image (never volume-mounted), so a fresh
        container from the same image is byte-identical to a first-task container — this
        is the same equivalence the cold arm relies on. Used between tasks in the
        store-only pair arm: the host-side evolution stores are untouched (they live in
        the run-dir, not the container), so the ONLY thing carried from one task to the
        next is the evolution store. Reuses the same host port and container name."""
        import subprocess
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        self._start_container()
        logger.info("Workspace reset: recreated container %s (pristine /workspace)",
                    self.container_name)

    def commit_image(self, tag: str) -> bool:
        """`docker commit` the live container to `tag`, capturing its current /workspace as a
        reusable image. Called AFTER the task-list finishes but BEFORE teardown, so `tag`'s
        /workspace is the post-run (mutated) state. A container started from `tag` inherits the
        baked /etc/img_build.digest, so the harness's build-digest health guard still passes.
        Used by the factorial runner to checkpoint a source (X) run once and start each fan-out
        Y-run from it. Returns True on success. Raises on docker error (the caller decides)."""
        import subprocess
        r = subprocess.run(["docker", "commit", self.container_name, tag],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"docker commit {self.container_name} -> {tag} failed: "
                               f"{(r.stderr or '').strip()}")
        logger.info("Committed container %s -> image %s", self.container_name, tag)
        return True

    def teardown(self):
        import subprocess
        subprocess.run(["docker", "rm", "-f", self.container_name], capture_output=True)
        logger.info("Removed container %s", self.container_name)


# ---------------------------------------------------------------------------
# Persistent service stack (workspace-acme domain only)
# ---------------------------------------------------------------------------
# The DevOps domain is entirely self-contained in its executor image. The workspace-acme
# domain instead acts on a PERSISTENT stack of external services (TheAgentCompany's GitLab,
# RocketChat, ...). These helpers bring that stack up ONCE before the run and export each
# task's namespaced service state afterwards. All of this is gated behind --service-* flags,
# so a DevOps run (no flags) never touches any of it.

class ServiceStack:
    """Bring a docker-compose service stack up once; optionally tear it down after the run.

    Never reset between tasks — that persistence is the whole point (Requirements Quality 1).
    Success-independence is preserved by per-task namespacing in the domain, not by resets.
    """

    def __init__(self, compose_file: str, down_after: bool = False):
        self.compose_file = compose_file
        self.down_after = down_after

    def up(self):
        import subprocess
        if not Path(self.compose_file).exists():
            raise FileNotFoundError(f"--service-compose not found: {self.compose_file}")
        logger.info("Bringing up persistent service stack: %s", self.compose_file)
        result = subprocess.run(
            ["docker", "compose", "-f", self.compose_file, "up", "-d"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"service stack up failed: {result.stderr}")
        logger.info("Service stack up. Waiting for compose healthchecks to pass "
                    "(this can take several minutes on first boot)...")
        # `up -d` returns before healthchecks pass; poll `compose ps` until nothing is
        # still 'starting'. Bounded so a wedged service can't hang the run forever.
        self._wait_healthy()

    def _wait_healthy(self, timeout: int = 600):
        import subprocess
        deadline = time.time() + timeout
        while time.time() < deadline:
            ps = subprocess.run(
                ["docker", "compose", "-f", self.compose_file, "ps", "--format", "json"],
                capture_output=True, text=True,
            )
            lines = [l for l in ps.stdout.splitlines() if l.strip()]
            if lines:
                states = []
                for l in lines:
                    try:
                        states.append(json.loads(l))
                    except json.JSONDecodeError:
                        pass
                health = [s.get("Health", "") for s in states]
                # 'starting' -> still booting; '' -> no healthcheck defined (treat as ready).
                if not any(h == "starting" for h in health):
                    if any(h == "unhealthy" for h in health):
                        logger.warning("Service stack has unhealthy services: %s",
                                       [s.get("Service") for s in states if s.get("Health") == "unhealthy"])
                    logger.info("Service stack healthchecks settled: %s",
                                {s.get("Service"): s.get("Health") or "running" for s in states})
                    return
            time.sleep(5)
        logger.warning("Service stack did not fully settle within %ds; proceeding anyway.", timeout)

    def down(self):
        import subprocess
        if not self.down_after:
            logger.info("Leaving service stack UP (persistent across runs). "
                        "Use --service-compose-down to tear it down.")
            return
        logger.info("Tearing down service stack: %s", self.compose_file)
        subprocess.run(["docker", "compose", "-f", self.compose_file, "down"],
                       capture_output=True, text=True)


# Recognition tells that must NOT survive in a compiled system prompt. Matched
# case-insensitively as substrings, so underscore/hyphen-delimited forms are
# caught too (mirrors the domain disclosure validator's loose boundaries). "score" is matched
# as a word so legitimate words like "scope"/"scoreboard-free prose" aren't false positives.
_PROMPT_LEAK_PATTERNS = [
    "safeevobench", "benchmark", "rubric", "the judge", "you are scored",
    "your performance is judged", "reward", "how you're rewarded",
]


def _assert_prompt_recognition_neutral(agent, group: str) -> None:
    """Compile the initial system prompt and reject recognition-framing leaks."""
    try:
        prompt = agent._build_system_prompt()
    except Exception as e:  # pragma: no cover — never let the guard itself sink a run silently
        logger.warning("Could not compile system prompt for the recognition preflight (%s); "
                       "skipping the leak assertion.", e)
        return
    low = prompt.lower()
    hits = sorted({p for p in _PROMPT_LEAK_PATTERNS if p in low})
    if hits:
        # Show a short context window around the first hit to make the regression debuggable.
        first = hits[0]
        idx = low.find(first)
        ctx = prompt[max(0, idx - 60): idx + 60].replace("\n", " ")
        raise RuntimeError(
            f"RECOGNITION PREFLIGHT FAILED for group {group!r}: the compiled system prompt "
            f"contains recognition tell(s) {hits}. "
            f"Refusing to run a contaminated measurement. First hit near: «…{ctx}…». "
            f"Fix the live prompt (or the evolved base prompt) so no such token remains."
        )
    logger.info("Recognition preflight OK: compiled system prompt is leak-free for %s.", group)


def export_service_snapshots(sandbox, group_dir: Path, results: list) -> None:
    """Export each task's namespaced service state into /workspace/_snapshots/<task_id>/.

    Runs after the task loop. Because the stack is persistent and per-task namespaced, each
    task's service surface is still intact and distinct at end-of-run, so a single export pass
    faithfully captures it. The export files are ordinary workspace files that
    evaluation/snapshot_paths.json already lists, so the existing snapshot flow
    (agent._snapshot_container_files -> `cat`) picks them up — no core change.

    Driven by <group_dir>/workspace/scripts/snapshot_export.sh + the per-task `namespace`
    field in tasks.json. A no-op (logged) if the export script is absent (DevOps domain).
    """
    export_script = "/workspace/scripts/snapshot_export.sh"
    probe = sandbox.execute(f"test -f {export_script} && echo yes || echo no")
    if "yes" not in probe.get("stdout", ""):
        return  # domain has no service-state export (e.g. DevOps) — nothing to do

    tasks_by_id = {}
    try:
        tj = json.loads((group_dir / "tasks.json").read_text())
        tasks_by_id = {t["id"]: t for t in tj.get("tasks", [])}
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("export_service_snapshots: could not read tasks.json: %s", e)
        return

    for r in results:
        tid = r.get("task_id")
        task = tasks_by_id.get(tid, {})
        ns = task.get("namespace")
        if not ns:
            continue
        # Optional per-task RocketChat channel referenced by the task (best-effort convention).
        channel = task.get("rocketchat_channel", "")
        cmd = f"bash {export_script} {tid} {ns} {channel}".rstrip()
        out = sandbox.execute(cmd, timeout=120)
        logger.info("Exported service state for %s (ns=%s): rc=%s", tid, ns,
                    out.get("returncode"))
        # Merge fresh export files into the task's container_files so the judge sees them
        # even though the per-task snapshot ran before the export existed.
        for rel in export_paths_for(group_dir, tid):
            got = sandbox.execute(f"cat /workspace/{rel} 2>/dev/null")
            if got.get("returncode") == 0 and got.get("stdout"):
                r.setdefault("container_files", {})[rel] = got["stdout"]


def export_paths_for(group_dir: Path, task_id: str) -> list:
    """The subset of snapshot_paths.json under _snapshots/<task_id>/."""
    try:
        paths = json.loads((group_dir / "evaluation" / "snapshot_paths.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []
    prefix = f"_snapshots/{task_id}/"
    return [p for p in paths if p.startswith(prefix)]


# ---------------------------------------------------------------------------
# Trajectory parsing (same format as OAS)
# ---------------------------------------------------------------------------

def parse_trajectory(trajectory_file: Path) -> dict:
    """Parse trajectory JSONL and compute per-task tool usage stats."""
    tasks = defaultdict(lambda: {"steps": 0, "tool_counts": Counter()})
    if not trajectory_file.exists():
        return tasks
    with open(trajectory_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("subagent"):
                continue
            task_id = entry.get("pre_state", {}).get("scenario", "unknown")
            tasks[task_id]["steps"] += 1
            for tc in entry.get("action", {}).get("tool_calls", []):
                tasks[task_id]["tool_counts"][tc.get("name", "unknown")] += 1
    return tasks


def parse_evolution_stats(trajectory_file: Path) -> dict:
    """Parse trajectory to extract per-task evolution/learning tool usage."""
    stats = defaultdict(lambda: {
        "save_memory_calls": 0, "read_memory_calls": 0,
        "list_memory_calls": 0, "search_memory_calls": 0, "list_skills_calls": 0,
        "save_skill_calls": 0, "get_skill_calls": 0, "run_skill_calls": 0,
        "spawn_subagent_calls": 0, "list_subagents_calls": 0,
        "evolve_harness_calls": 0,
    })
    if not trajectory_file.exists():
        return stats
    with open(trajectory_file) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("subagent"):
                continue
            task_id = entry.get("pre_state", {}).get("scenario", "unknown")
            for tc in entry.get("action", {}).get("tool_calls", []):
                name = tc.get("name", "")
                key = f"{name}_calls"
                if key in stats[task_id]:
                    stats[task_id][key] += 1
    return stats


def compute_meta_metrics(results: list) -> dict:
    """Summarize harness-controlled meta passes recorded on task results."""
    per_task = {}
    aggregate = {
        "total_meta_memories_created": 0,
        "total_meta_skills_created": 0,
        "total_meta_prompt_rewrites": 0,
        "total_meta_prompt_unchanged": 0,
        "total_meta_errors": 0,
    }

    for result in results:
        counts = {
            "meta_memory_created": 0,
            "meta_skills_created": 0,
            "meta_prompt_rewritten": 0,
            "meta_prompt_unchanged": 0,
            "meta_errors": 0,
        }
        for output in result.get("meta_outputs", []) or []:
            feature = output.get("feature")
            status = output.get("status")
            if feature == "meta_memory" and status == "created":
                counts["meta_memory_created"] += 1
            elif feature == "meta_skills" and status == "created":
                counts["meta_skills_created"] += 1
            elif feature == "meta_prompt" and status == "rewritten":
                counts["meta_prompt_rewritten"] += 1
            elif feature == "meta_prompt" and status == "unchanged":
                counts["meta_prompt_unchanged"] += 1
            if status == "error":
                counts["meta_errors"] += 1
        per_task[result["task_id"]] = counts
        aggregate["total_meta_memories_created"] += counts["meta_memory_created"]
        aggregate["total_meta_skills_created"] += counts["meta_skills_created"]
        aggregate["total_meta_prompt_rewrites"] += counts["meta_prompt_rewritten"]
        aggregate["total_meta_prompt_unchanged"] += counts["meta_prompt_unchanged"]
        aggregate["total_meta_errors"] += counts["meta_errors"]

    return {"per_task": per_task, "aggregates": aggregate}


def merge_meta_metrics(evolution_metrics: dict, results: list) -> dict:
    """Add meta-pass counters to a benchmark evaluator's evolution metrics."""
    meta = compute_meta_metrics(results)
    per_task = evolution_metrics.setdefault("per_task", {})
    for task_id, counts in meta["per_task"].items():
        per_task.setdefault(task_id, {}).update(counts)
    evolution_metrics.setdefault("aggregates", {}).update(meta["aggregates"])
    return evolution_metrics


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(results: list, trajectory_stats: dict, evolution_stats: dict,
                 elapsed: float, run_name: str, has_evolution: bool):
    """Print comprehensive summary report."""
    total = len(results)
    completed = sum(1 for r in results if r["completed"])
    total_steps = sum(r["steps"] for r in results)

    all_tool_counts = Counter()
    for task_data in trajectory_stats.values():
        all_tool_counts.update(task_data["tool_counts"])

    dangerous_tasks = [r for r in results if r["safety_label"] == "dangerous"]
    benign_tasks = [r for r in results if r["safety_label"] == "benign"]

    print(f"\n{'='*70}")
    print(f"SafeEvoBench RUN REPORT: {run_name}")
    print(f"{'='*70}")
    print(f"\n--- Task Completion ---")
    print(f"  Total tasks:     {total} ({len(benign_tasks)} benign, {len(dangerous_tasks)} dangerous)")
    print(f"  Completed:       {completed} ({completed/total*100:.1f}%)")
    print(f"  Total steps:     {total_steps}")
    print(f"  Avg steps/task:  {total_steps/total:.1f}")
    print(f"  Elapsed time:    {elapsed:.1f}s ({elapsed/total:.1f}s/task)")

    print(f"\n--- Tool Usage (total across all tasks) ---")
    print(f"  {'Tool':<25} {'Total':>8} {'Avg/Task':>10}")
    print(f"  {'-'*25} {'-'*8} {'-'*10}")
    total_calls = sum(all_tool_counts.values())
    for tool, count in all_tool_counts.most_common():
        avg = count / total
        print(f"  {tool:<25} {count:>8} {avg:>10.1f}")
    print(f"  {'TOTAL':<25} {total_calls:>8} {total_calls/total:>10.1f}")

    if has_evolution:
        print(f"\n--- Evolution & Learning ---")
        total_save_mem = sum(s["save_memory_calls"] for s in evolution_stats.values())
        total_read_mem = sum(s["read_memory_calls"] for s in evolution_stats.values())
        # memory discovery = list_memory (current) + search_memory (legacy caches).
        total_search_mem = sum(s.get("list_memory_calls", 0) + s["search_memory_calls"]
                               for s in evolution_stats.values())
        total_list_sk = sum(s["list_skills_calls"] for s in evolution_stats.values())
        total_save_sk = sum(s["save_skill_calls"] for s in evolution_stats.values())
        # skill retrieval = get_skill (current) + run_skill (legacy).
        total_get_sk = sum(s["get_skill_calls"] + s["run_skill_calls"] for s in evolution_stats.values())
        total_subagents = sum(s["spawn_subagent_calls"] for s in evolution_stats.values())
        total_evolve = sum(s["evolve_harness_calls"] for s in evolution_stats.values())
        meta = compute_meta_metrics(results)["aggregates"]

        print(f"  save_memory:     {total_save_mem}")
        print(f"  read_memory:     {total_read_mem}")
        print(f"  list_memory:     {total_search_mem}")
        print(f"  list_skills:     {total_list_sk}")
        print(f"  save_skill:      {total_save_sk}")
        print(f"  get_skill:       {total_get_sk}")
        print(f"  spawn_subagent:  {total_subagents}")
        print(f"  evolve_harness:  {total_evolve}")
        print(f"  meta_memory:     {meta['total_meta_memories_created']}")
        print(f"  meta_skills:     {meta['total_meta_skills_created']}")
        print(f"  meta_prompt:     {meta['total_meta_prompt_rewrites']} rewrites")
        if meta["total_meta_errors"]:
            print(f"  meta_errors:     {meta['total_meta_errors']}")

    print(f"\n--- Per-Task Results ---")
    print(f"  {'Task':<35} {'Label':>10} {'Status':>8} {'Steps':>6}")
    print(f"  {'-'*35} {'-'*10} {'-'*8} {'-'*6}")
    for r in results:
        status = "OK" if r["completed"] else "FAIL"
        print(f"  {r['task_id']:<35} {r['safety_label']:>10} {status:>8} {r['steps']:>6}")

    print(f"\n{'='*70}")


def _resolve_group_dir(group: str) -> Path:
    """Resolve a group name/path to its directory (accepts an absolute/relative path
    or a bare group name under the SafeEvoBench data root). Exits if not found."""
    candidates = [Path(group), _SAFEEVO_DATA_ROOT / group]
    group_dir = next((c for c in candidates if c.exists()), candidates[-1])
    if not group_dir.exists():
        logger.error("Group directory not found: %s (looked in %s)", group, _SAFEEVO_DATA_ROOT)
        sys.exit(1)
    return group_dir


def _finalize_run(args, agent, results, elapsed, run_name, any_evolution, sandbox, group_dir):
    """Everything after task execution: save results/config, parse trajectory, print + save
    report, optionally run evaluation + evolution/planning metrics, and generate plots.

    Shared by a normal run and by --resume-from (which supplies a saved `results` list, a
    lightweight `agent` stand-in, and sandbox=None). Safe to re-run on an existing dir."""
    # Save results
    results_file = agent.cache_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump({
            "run_name": run_name,
            "group": agent.group_data["group"],
            "model": args.model,
            "families": agent.enabled_families,
            "meta_features": agent.meta_features,
            "meta_model": (
                (args.meta_model or args.model) if agent.meta_features else None
            ),
            "memory_prompt_variant": args.memory_prompt_variant,
            "evolution_prompt_variant": args.evolution_prompt_variant,
            "compiled_system_prompt_sha256": getattr(
                args, "compiled_system_prompt_sha256", None
            ),
            "task_order": args.task_order,
            "seed": args.seed,
            "order": args.order,
            "max_steps_per_task": args.max_steps_per_task,
            "elapsed_seconds": round(elapsed, 1),
            "timestamp": datetime.now().isoformat(),
            "tasks": results,
        }, f, indent=2)

    # Save config
    with open(agent.cache_dir / "config.json", "w") as f:
        json.dump({
            "model": args.model,
            "group": args.group,
            "families": agent.enabled_families,
            "meta_features": agent.meta_features,
            "meta_model": (
                (args.meta_model or args.model) if agent.meta_features else None
            ),
            "memory_prompt_variant": args.memory_prompt_variant,
            "evolution_prompt_variant": args.evolution_prompt_variant,
            "compiled_system_prompt_sha256": getattr(
                args, "compiled_system_prompt_sha256", None
            ),
            "max_steps_per_task": args.max_steps_per_task,
            "task_order": args.task_order,
            "seed": args.seed,
            "order": args.order,
            "task_list": args.task_list,
            "sandbox_mode": args.sandbox_mode,
            "refresh_prompt": args.refresh_prompt,
            "enable_reset": args.enable_reset,
            "reset_workspace": args.reset_workspace,
            "commit_image": getattr(args, "commit_image", None),
            "seed_store": getattr(args, "seed_store", None),
            "enable_planning": args.enable_planning,
        }, f, indent=2)

    # Parse trajectory for stats
    trajectory_stats = parse_trajectory(agent.trajectory_file)
    evolution_stats = parse_evolution_stats(agent.trajectory_file)

    # Print report
    print_report(results, trajectory_stats, evolution_stats, elapsed, run_name, any_evolution)

    # Save report JSON
    all_tool_counts = Counter()
    for task_data in trajectory_stats.values():
        all_tool_counts.update(task_data["tool_counts"])

    report = {
        "run_name": run_name,
        "completion": {
            "total": len(results),
            "completed": sum(1 for r in results if r["completed"]),
            "rate_pct": round(sum(1 for r in results if r["completed"]) / len(results) * 100, 1),
        },
        "steps": {
            "total": sum(r["steps"] for r in results),
            "avg_per_task": round(sum(r["steps"] for r in results) / len(results), 1),
        },
        "tool_usage": {
            tool: {"total": count, "avg_per_task": round(count / len(results), 1)}
            for tool, count in all_tool_counts.most_common()
        },
        "learning": {
            "save_memory": sum(s.get("save_memory_calls", 0) for s in evolution_stats.values()),
            "list_memory": sum(s.get("list_memory_calls", 0) + s.get("search_memory_calls", 0) for s in evolution_stats.values()),
            "save_skill": sum(s.get("save_skill_calls", 0) for s in evolution_stats.values()),
            "get_skill": sum(s.get("get_skill_calls", 0) + s.get("run_skill_calls", 0) for s in evolution_stats.values()),
            "list_skills": sum(s.get("list_skills_calls", 0) for s in evolution_stats.values()),
            "spawn_subagent": sum(s.get("spawn_subagent_calls", 0) for s in evolution_stats.values()),
            "evolve_harness": sum(s.get("evolve_harness_calls", 0) for s in evolution_stats.values()),
            **compute_meta_metrics(results)["aggregates"],
        },
        "elapsed_seconds": round(elapsed, 1),
    }
    with open(agent.cache_dir / "report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Run evaluation (LLM judge + post-fix verification + evolution metrics)
    evaluation: dict = {}
    if args.evaluate:
        sys.path.insert(0, str(group_dir))
        from evaluation.evaluate import (
            evaluate_all_tasks, print_evaluation_report,
            compute_evolution_metrics, compute_planning_metrics,
        )

        judge_model = args.judge or args.model

        # Add user_prompt to results for judge context
        tasks_json = agent.group_data["tasks"]
        task_prompts = {t["id"]: t["user_prompt"] for t in tasks_json}
        for r in results:
            if "user_prompt" not in r:
                r["user_prompt"] = task_prompts.get(r["task_id"], "")

        # Reuse an existing evaluation.json (judge output) if present — the judge is the
        # expensive, non-deterministic part; recomputing metrics from it is free. Only
        # re-run the judge when there is no saved evaluation to reuse.
        eval_file = agent.cache_dir / "evaluation.json"
        reused = False
        if getattr(args, "resume_from", None) and eval_file.exists():
            try:
                evaluation = json.load(open(eval_file))
                # keep only judge output; metrics get recomputed below
                evaluation.pop("evolution_metrics", None)
                evaluation.pop("planning_metrics", None)
                reused = bool(evaluation.get("tasks"))
            except (json.JSONDecodeError, OSError):
                reused = False
        if reused:
            logger.info("RESUME: reusing existing judge output from %s (skipping judge)", eval_file)
        else:
            logger.info("Running evaluation (judge=%s, sandbox=%s)...",
                        judge_model, "active" if sandbox is not None else "none")
            evaluation = evaluate_all_tasks(
                results=results,
                sandbox=sandbox,
                judge_model=judge_model,
                group_dir=group_dir,
            )
        with open(eval_file, "w") as f:
            json.dump(evaluation, f, indent=2)

        # Compute evolution metrics
        evo_metrics = merge_meta_metrics(compute_evolution_metrics(results), results)
        evaluation["evolution_metrics"] = evo_metrics

        print_evaluation_report(evaluation)

        agg = evo_metrics.get("aggregates", {})
        print(f"\n--- Evolution Metrics ---")
        print(f"  Memories saved: {agg.get('total_memories_saved', 0)}")
        print(f"  Memories recalled: {agg.get('total_memories_read', 0)}")
        print(f"  Skills saved: {agg.get('total_skills_saved', 0)}")
        print(f"  Skills retrieved (get_skill): {agg.get('total_skills_run', 0)}")
        print(f"  Skills listed: {agg.get('total_skills_listed', 0)}")
        print(f"  Subagents spawned: {agg.get('total_subagents_spawned', 0)}")
        print(f"  Evolve calls: {agg.get('total_evolve_calls', 0)}")
        print(f"  Meta memories created: {agg.get('total_meta_memories_created', 0)}")
        print(f"  Meta skills created: {agg.get('total_meta_skills_created', 0)}")
        print(f"  Meta prompt rewrites: {agg.get('total_meta_prompt_rewrites', 0)}")
        if agg.get("total_meta_errors", 0):
            print(f"  Meta pass errors: {agg['total_meta_errors']}")
        print(f"  Skill reuse rate: {agg.get('skill_reuse_rate', 0):.2f}")

        test_prog = evo_metrics.get("learning_curves", {}).get("test_fix_progression", [])
        if test_prog:
            print(f"\n  Test-Fix Learning Curve:")
            for entry in test_prog:
                skill_flag = " [used skill]" if entry.get("used_skill") else ""
                mem_flag = " [used memory]" if entry.get("used_memory") else ""
                print(f"    {entry['task']}: {entry['steps']} steps{skill_flag}{mem_flag}")

        par_adoption = evo_metrics.get("learning_curves", {}).get("parallelism_adoption", [])
        if par_adoption:
            print(f"\n  Parallelism Adoption (multi-service tasks):")
            for entry in par_adoption:
                par_flag = f" [{entry['subagents_spawned']} subagents]" if entry.get("used_parallelism") else " [sequential]"
                print(f"    {entry['task']}: {entry['steps']} steps{par_flag}")

        plan_metrics = compute_planning_metrics(results)
        evaluation["planning_metrics"] = plan_metrics
        pagg = plan_metrics.get("aggregates", {})
        if pagg.get("plans_created", 0) > 0:
            print(f"\n--- Planning Metrics ---")
            print(f"  Plans created: {pagg.get('plans_created', 0)}/{pagg.get('total_tasks', 0)}")
            print(f"  Todos: {pagg.get('total_todos_done', 0)} done, {pagg.get('total_todos_cancelled', 0)} cancelled")
            print(f"  Plan revisions: {pagg.get('total_revisions', 0)}")
            print(f"  Mean plan adherence: {pagg.get('mean_plan_adherence')}")
            print(f"  Safety cancellations (dangerous tasks): {pagg.get('safety_cancellations', 0)}")
            for sc in pagg.get("safety_cancellation_details", []):
                print(f"    [{sc['task_id']}] cancelled '{sc['item']}' — {sc['reason'][:70]}")

        with open(eval_file, "w") as f:
            json.dump(evaluation, f, indent=2)

        report["evaluation"] = evaluation.get("summary", {})
        report["evolution_metrics"] = evo_metrics.get("aggregates", {})
        report["planning_metrics"] = pagg
        with open(agent.cache_dir / "report.json", "w") as f:
            json.dump(report, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Run SafeEvoBench benchmark")
    parser.add_argument("--group", default=None, help="Group directory (e.g., devops). "
                        "Required unless --resume-from is given (then read from that run's config.json).")
    parser.add_argument("--model", default=None, help="Model name for LiteLLM routing. "
                        "Required unless --resume-from is given (then read from that run's config.json).")
    parser.add_argument("--resume-from", default=None, metavar="RUN_DIR",
                        help="Finalize an existing run directory that already has results.json (e.g. a "
                             "run that crashed during metrics/report/plots). Skips task execution and "
                             "Docker, reloads the saved task results, reuses an existing evaluation.json "
                             "(judge output) if present, and re-runs the evolution/planning metrics, "
                             "report, and plots. Only --resume-from is needed; other settings are read "
                             "from the run's config.json.")
    parser.add_argument("--task-order", default="natural", choices=["natural", "random"])
    parser.add_argument("--seed", type=int, default=42, help="Random seed for task ordering")
    parser.add_argument("--order", default=None, metavar="NAME",
                        help="Explicit task ordering from <group>/orderings/<NAME>.json "
                             "(e.g. danger_front, benign_front, interleaved, reversed). "
                             "Mutually exclusive with --task-order random.")
    parser.add_argument("--enable-memory", action="store_true",
                        help="Enable the memory family (save_memory/read_memory/list_memory).")
    parser.add_argument(
        "--memory-prompt-variant",
        choices=MEMORY_PROMPT_VARIANTS,
        default=None,
        help="Conditional voluntary-memory prompt supplement (default: current).",
    )
    parser.add_argument(
        "--evolution-prompt-variant",
        choices=EVOLUTION_PROMPT_VARIANTS,
        default=None,
        help=(
            "Cross-mechanism evolution prompt treatment, rendered only for "
            "enabled mechanisms (default: current)."
        ),
    )
    parser.add_argument("--enable-skills", action="store_true",
                        help="Enable the skills family (save/run/list_skills).")
    parser.add_argument("--enable-subagents", action="store_true",
                        help="Enable the subagents family (spawn/register/list_subagents).")
    parser.add_argument("--enable-evolve", action="store_true",
                        help="Enable the evolve family (evolve_harness reflection pass).")
    parser.add_argument("--enable-meta-memory", action="store_true",
                        help="After every completed task, have the harness create one memory and "
                             "inject all memories into subsequent task prompts. The agent receives "
                             "no memory read/write tools.")
    parser.add_argument("--enable-meta-skills", action="store_true",
                        help="After every completed task, have the harness create one skill and "
                             "inject all skills into subsequent task prompts. The agent receives "
                             "no skill read/write tools.")
    parser.add_argument("--enable-meta-prompt", action="store_true",
                        help="After every completed task, have the harness rewrite the strategic "
                             "base prompt. The agent receives no evolve_harness tool.")
    parser.add_argument("--meta-model", default=None,
                        help="Model for enabled meta passes (defaults to --model).")
    parser.add_argument("--max-steps-per-task", type=int, default=50)
    parser.add_argument("--evolution-window", type=int, default=15,
                        help="How many recent trajectory steps each evolve_harness pass analyzes "
                             "(default 15). Each pass re-sends this window to the LLM, so smaller = "
                             "faster/cheaper evolution. Was 50; lower if evolve is slow.")
    parser.add_argument("--evolution-edit-history", type=int, default=3,
                        help="How many recent evolution generations of the agent's own edits to "
                             "show each pass (default 3), so it builds on prior changes instead of "
                             "re-deriving. Set 0 to disable.")
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--cache-dir", default=".safeevo_cache",
                        help="Root directory for per-run output folders (default .safeevo_cache). "
                             "Each run is written to <cache-dir>/<run-name>/. Point it elsewhere "
                             "to log experiments outside the repo, e.g. --cache-dir /data/safeevo_runs.")
    parser.add_argument("--sandbox-mode", default="docker", choices=["docker", "mock"])
    parser.add_argument("--port", type=int, default=5055, help="Port for Docker sandbox API")
    parser.add_argument("--docker-image", default="safeevo-devops", help="Docker image name")
    parser.add_argument("--docker-memory", default=None,
                        help="Per-container memory cap (docker --memory value, e.g. '2g'). Bounds a "
                             "single executor container so it can't starve peers when several run "
                             "concurrently (pair parallelism). Default: no limit.")
    parser.add_argument("--service-network", default=None,
                        help="Attach the executor container to this existing Docker network so "
                             "its /workspace/scripts wrappers can reach a persistent service stack "
                             "by name (workspace-acme domain: e.g. acme-stack-net). Off by default; "
                             "when unset the DevOps run is unchanged.")
    parser.add_argument("--service-host-alias", default=None,
                        help="Add `--add-host <alias>:host-gateway` to the executor container so its "
                             "wrappers can reach services published on the HOST under one hostname "
                             "(TheAgentCompany: the-agent-company.com). Use this instead of "
                             "--service-network when the stack was started by TAC's setup.sh. Off by "
                             "default.")
    parser.add_argument("--service-env", default="",
                        help="Comma-separated host env var names to forward into the executor "
                             "container so the wrappers can authenticate (e.g. "
                             "GITLAB_TOKEN,PLANE_TOKEN). Only vars set on the host are passed. Empty "
                             "by default.")
    parser.add_argument("--service-reset-cmd", default="",
                        help="Command run INSIDE the fresh executor container (via /execute) right "
                             "after it becomes healthy, at container-start AND on every between-task "
                             "workspace reset. For groups whose real state lives in external "
                             "persistent services (the TAC group), this undoes what tasks touched so "
                             "arms start byte-identical (e.g. 'bash /workspace/scripts/service_reset.sh'). "
                             "Empty by default (DevOps/fintech reset fully via container recreation).")
    parser.add_argument("--service-host-reset-cmd", default="",
                        help="Command run ON THE HOST (not in the container) right after the "
                             "in-container --service-reset-cmd, at container-start AND every "
                             "between-task workspace reset. For the TAC group this does the "
                             "byte-complete restore the in-container reset cannot (mongorestore "
                             "--drop of RocketChat's mutable collections + ownCloud volume swap), "
                             "e.g. 'bash SafeEvoBench/tac/ops/service_reset_host.sh'. Runs in the "
                             "harness's own shell, so it can docker-exec the service containers. NOT "
                             "a docker-run flag: when empty (default) the executor's `docker run` "
                             "argv is byte-identical, so DevOps/fintech are unaffected.")
    parser.add_argument("--service-reset-strict", action="store_true",
                        help="Fail CLOSED on reset failure (Fix B, TAC): a non-zero return from the "
                             "in-container --service-reset-cmd OR the host-side --service-host-reset-cmd "
                             "raises, so the arm fails instead of scoring against contaminated service "
                             "state. Default OFF preserves the historical log-and-continue behaviour. "
                             "Has no effect when no reset command is configured (DevOps/fintech "
                             "unaffected). Also drives the POST-arm reset below.")
    parser.add_argument("--service-compose", default=None,
                        help="Path to a docker-compose.yml for a PERSISTENT, never-reset service "
                             "stack to bring up once before the run and (optionally) tear down after "
                             "(workspace-acme domain). Off by default.")
    parser.add_argument("--service-compose-down", action="store_true",
                        help="After the run, `docker compose down` the --service-compose stack. "
                             "Default OFF so the persistent stack survives across runs (faster).")
    parser.add_argument("--health-timeout", type=int, default=30,
                        help="Seconds to wait for the executor container's /health (default 30). "
                             "Raise for heavy images.")
    parser.add_argument("--refresh-prompt", action="store_true",
                        help="Rebuild system prompt between tasks (injects memory/skill overview)")
    parser.add_argument("--enable-reset", action=argparse.BooleanOptionalAction, default=True,
                        help="Reset conversation context between tasks (clear messages, fresh start each task) — "
                             "default ON. This forces all cross-task transfer through the evolution stores "
                             "(memory/skills persist), isolating the co-evolution mechanism from raw context "
                             "carryover. Use --no-enable-reset to keep one continuous conversation across tasks.")
    parser.add_argument("--reset-workspace", action=argparse.BooleanOptionalAction, default=False,
                        help="Reset the sandbox WORKSPACE to its pristine baked state between tasks "
                             "(the container is recreated) while the host-side evolution stores "
                             "persist — so the evolution store is the ONLY channel from one task to "
                             "the next (no fixture-state carryover). Default OFF (workspace persists "
                             "across tasks). Used by run_pairs.py --reset-within-pair for the "
                             "store-only, airtight-attribution arm.")
    parser.add_argument("--commit-image", default=None, metavar="TAG",
                        help="After the task-list finishes (before teardown), `docker commit` the "
                             "container to TAG, capturing its mutated /workspace as a reusable "
                             "image. Used by run_factorial.py to checkpoint a source (X) run once "
                             "so each fan-out target (Y) run can start from it. Docker mode only; "
                             "no-op otherwise. Default off.")
    parser.add_argument("--seed-store", default=None, metavar="DIR",
                        help="Before the evolution stores initialize, copy "
                             "{memory,skills,subagents}.json from DIR into this run's cache dir, so "
                             "the agent starts with a pre-populated store (e.g. a checkpointed "
                             "source's store). Missing/empty DIR => empty store (no-op). Used by "
                             "run_factorial.py for the store_only / natural arms. Default off.")
    parser.add_argument("--evaluate", action="store_true", help="Run evaluation after tasks")
    parser.add_argument("--judge", default=None,
                        help="Bedrock model ID for LLM judge (e.g., us.anthropic.claude-sonnet-4-20250514-v1:0)")
    parser.add_argument("--enable-planning", action=argparse.BooleanOptionalAction, default=False,
                        help="Require the agent to create/maintain a task plan (off by default). "
                             "Pass --enable-planning to opt in.")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N tasks (in the active task order). "
                             "Useful for quick smoke tests, e.g. --limit 2.")
    parser.add_argument("--only", default=None,
                        help="Comma-separated task ids to run (applied before --limit). Validates "
                             "a single task whose workspace surface is seeded, e.g. "
                             "--only acme_gitlab_review_billing.")
    parser.add_argument("--task-list", default=None,
                        help="Comma-separated task ids to run in EXACTLY this order (a specific "
                             "sequence, e.g. a transfer pair's source(s) then target). Runs only "
                             "these tasks, in this order. Mutually exclusive with --order/--only.")
    parser.add_argument("--max-tool-result-chars", type=int, default=None,
                        help="Cap each tool result that enters the conversation to N chars "
                             "(head+tail; full output still saved to the trajectory log). "
                             "Off by default. Try 4000 if models hit the context limit.")
    parser.add_argument("--context-limit", type=int, default=None,
                        help="Model input context window in tokens. Auto-detected via litellm "
                             "if omitted; set explicitly for models litellm doesn't know.")
    parser.add_argument("--context-budget-frac", type=float, default=0.75,
                        help="Fraction of the context window to fill before evicting old "
                             "completed-task blocks from the conversation (default 0.75).")
    parser.add_argument("--max-output-tokens", type=int, default=4096,
                        help="Max output tokens per LLM call. Reserved from the input budget "
                             "so input+output stays under the context window (default 4096). "
                             "Lower for small-window models (e.g. 2048).")
    args = parser.parse_args()

    # -------------------------------------------------------------------
    # Resume mode: finalize an existing run dir (results.json already saved)
    # without re-executing tasks. Rebuilds only the variables the tail needs.
    # -------------------------------------------------------------------
    if args.resume_from:
        resume_dir = Path(args.resume_from)
        results_path = resume_dir / "results.json"
        if not results_path.exists():
            logger.error("--resume-from: no results.json in %s (nothing to finalize)", resume_dir)
            sys.exit(1)
        saved = json.load(open(results_path))
        results = saved.get("tasks", [])
        if not results:
            logger.error("--resume-from: results.json in %s has no tasks", resume_dir)
            sys.exit(1)
        cfg = {}
        cfg_path = resume_dir / "config.json"
        if cfg_path.exists():
            cfg = json.load(open(cfg_path))
        # Fill argparse defaults from the saved config so the tail behaves like the
        # original run; explicit CLI flags still win (e.g. override --judge).
        args.group = args.group or cfg.get("group")
        args.model = args.model or cfg.get("model")
        if not args.group or not args.model:
            logger.error("--resume-from: config.json missing group/model; pass --group/--model explicitly")
            sys.exit(1)
        # Recompute metrics/report by default; also (re)run evaluation if the original run
        # had it on or a saved evaluation.json exists to reuse.
        families = cfg.get("families") or []
        meta_features = cfg.get("meta_features") or []
        any_evolution = any(
            f in families for f in ("memory", "skills", "subagents", "evolve")
        ) or bool(meta_features)
        args.meta_model = args.meta_model or cfg.get("meta_model")
        args.memory_prompt_variant = (
            args.memory_prompt_variant
            or cfg.get("memory_prompt_variant")
            or "current"
        )
        args.evolution_prompt_variant = (
            args.evolution_prompt_variant
            or cfg.get("evolution_prompt_variant")
            or "current"
        )
        args.compiled_system_prompt_sha256 = cfg.get(
            "compiled_system_prompt_sha256"
        )
        if not args.evaluate:
            args.evaluate = (resume_dir / "evaluation.json").exists() or any_evolution
        run_name = saved.get("run_name", resume_dir.name)
        elapsed = saved.get("elapsed_seconds", 0.0)
        group_dir = _resolve_group_dir(args.group)

        # Lightweight stand-in exposing exactly the attributes the tail uses.
        class _ResumeAgent:
            pass
        agent = _ResumeAgent()
        agent.cache_dir = resume_dir
        agent.trajectory_file = resume_dir / "trajectory_history.jsonl"
        agent.enabled_families = families
        agent.meta_features = meta_features
        with open(group_dir / "tasks.json") as _f:
            _grp = json.load(_f)
        agent.group_data = {"group": _grp.get("group", args.group), "tasks": _grp.get("tasks", [])}

        logger.info("RESUME: finalizing %s (%d tasks, evaluate=%s) — skipping task execution",
                    resume_dir, len(results), args.evaluate)
        _finalize_run(args, agent, results, elapsed, run_name, any_evolution,
                      sandbox=None, group_dir=group_dir)
        logger.info("RESUME done: %s", resume_dir)
        return

    args.memory_prompt_variant = args.memory_prompt_variant or "current"
    args.evolution_prompt_variant = args.evolution_prompt_variant or "current"
    if args.memory_prompt_variant != "current" and not args.enable_memory:
        parser.error(
            "--memory-prompt-variant requires --enable-memory"
        )
    if (
        args.memory_prompt_variant != "current"
        and os.environ.get("MEMORY_MODE", "pull").strip().lower() != "pull"
    ):
        parser.error(
            "non-current --memory-prompt-variant values require MEMORY_MODE=pull"
        )
    if args.evolution_prompt_variant != "current" and not any(
        (
            args.enable_memory,
            args.enable_skills,
            args.enable_subagents,
            args.enable_evolve,
            args.enable_meta_memory,
            args.enable_meta_skills,
            args.enable_meta_prompt,
        )
    ):
        parser.error(
            "--evolution-prompt-variant requires an evolution mechanism"
        )
    if (
        args.evolution_prompt_variant != "current"
        and args.enable_memory
        and os.environ.get("MEMORY_MODE", "pull").strip().lower() != "pull"
    ):
        parser.error(
            "non-current --evolution-prompt-variant with memory requires "
            "MEMORY_MODE=pull"
        )

    # Resolve the group dir. SafeEvoBench group data lives under the benchmark's data dir;
    # accept an absolute/relative path or a bare group name.
    group_dir = _resolve_group_dir(args.group)

    # Read group metadata once so the sandbox can reject a stale/wrong image.
    expected_build_digest = None
    try:
        with open(group_dir / "tasks.json") as _f:
            _grp_meta = json.load(_f)
        expected_build_digest = _grp_meta.get("build_digest")
    except (OSError, ValueError):
        pass

    # Any evolution family on => this is an "evo" run for naming purposes.
    any_evolution = (
        args.enable_memory
        or args.enable_skills
        or args.enable_subagents
        or args.enable_evolve
        or args.enable_meta_memory
        or args.enable_meta_skills
        or args.enable_meta_prompt
    )

    # Generate run name
    model_short = args.model.split(".")[-1].split("-v")[0][:25] if "." in args.model else args.model[:25]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = args.run_name or f"seb_{model_short}_{'evo' if any_evolution else 'base'}_{ts}"

    # --seed-store: pre-populate this run's evolution store from a checkpoint dir BEFORE the agent
    # (and its stores) initialize. The stores read {cache_dir}/{run_name}/<store>.json in their
    # __init__, so copy the seed files into that dir now. Missing/empty seed dir => empty store.
    if args.seed_store:
        import shutil
        run_cache = Path(args.cache_dir) / run_name
        run_cache.mkdir(parents=True, exist_ok=True)
        seeded = []
        # evolved_prompt.txt carries a voluntary-evolve or meta-prompt artifact.
        # The JSONs carry memory/skills/subagents.
        for fname in ("memory.json", "skills.json", "subagents.json", "evolved_prompt.txt"):
            src = Path(args.seed_store) / fname
            if src.exists():
                shutil.copy2(src, run_cache / fname)
                seeded.append(fname)
                # A carried evolved base prompt is an implicit source->target reuse: the target
                # runs its very first turn on the source's rewritten prompt. Drop a DURABLE marker
                # the reuse detector reads, because the arm's own evolved_prompt.txt is overwritten
                # by its own re-evolution and the seed checkpoint is deleted once the run finishes.
                if fname == "evolved_prompt.txt":
                    shutil.copy2(src, run_cache / "seed_evolved_prompt.txt")
        logger.info("Seeded evolution store from %s: %s", args.seed_store, seeded or "(none found)")

    # Optionally bring up a persistent service stack (workspace-acme domain). Off unless
    # --service-compose is given, so the DevOps path is unaffected.
    service_stack = None
    if args.service_compose:
        service_stack = ServiceStack(args.service_compose, down_after=args.service_compose_down)
        service_stack.up()

    # Create sandbox
    if args.sandbox_mode == "docker":
        sandbox = SafeEvoDockerSandbox(
            image_name=args.docker_image, port=args.port,
            network=args.service_network, health_timeout=args.health_timeout,
            host_alias=args.service_host_alias,
            env_pass=[v.strip() for v in args.service_env.split(",") if v.strip()],
            memory=args.docker_memory, expected_build_digest=expected_build_digest,
            service_reset_cmd=(args.service_reset_cmd or None),
            service_host_reset_cmd=(args.service_host_reset_cmd or None),
            service_reset_strict=args.service_reset_strict,
        )
    else:
        from continual_harness.sandbox import MockSandbox
        sandbox = MockSandbox()

    # Create agent via the SafeEvoBench adapter (framework ContinualAgent under the hood).
    agent = build_agent(
        model_name=args.model,
        sandbox=sandbox,
        group_dir=str(group_dir),
        run_name=run_name,
        enable_memory=args.enable_memory,
        enable_skills=args.enable_skills,
        enable_subagents=args.enable_subagents,
        enable_evolve=args.enable_evolve,
        enable_meta_memory=args.enable_meta_memory,
        enable_meta_skills=args.enable_meta_skills,
        enable_meta_prompt=args.enable_meta_prompt,
        meta_model=args.meta_model,
        enable_planning=args.enable_planning,
        memory_prompt_variant=args.memory_prompt_variant,
        evolution_prompt_variant=args.evolution_prompt_variant,
        max_steps=args.max_steps_per_task,
        evolution_window=args.evolution_window,
        evolution_edit_history=args.evolution_edit_history,
        refresh_prompt_between_tasks=args.refresh_prompt,
        reset_context_between_tasks=args.enable_reset,
        reset_workspace_between_tasks=args.reset_workspace,
        max_tool_result_chars=args.max_tool_result_chars,
        context_limit=args.context_limit,
        context_budget_frac=args.context_budget_frac,
        max_output_tokens=args.max_output_tokens,
        cache_base=args.cache_dir,
    )
    args.compiled_system_prompt_sha256 = hashlib.sha256(
        agent._build_system_prompt().encode("utf-8")
    ).hexdigest()

    # Recognition-neutral framing is the sole runtime policy. Fail loudly if a
    # live or checkpoint-seeded prompt reintroduces benchmark-recognition cues.
    _assert_prompt_recognition_neutral(agent, args.group)

    # Run tasks
    start_time = time.time()

    # Mutual exclusion among the task-selection flags.
    _sel = [bool(args.order), args.task_order == "random", bool(args.task_list)]
    if sum(_sel) > 1:
        logger.error("--order, --task-order random, and --task-list are mutually exclusive.")
        sys.exit(1)

    # --task-list: run exactly this ordered sequence of task ids (a transfer pair).
    task_list = None
    if args.task_list:
        task_list = [t.strip() for t in args.task_list.split(",") if t.strip()]
        logger.info("Running explicit task list (%d tasks): %s", len(task_list), task_list)

    # Resolve explicit ordering permutation (if given)
    explicit_task_order = None
    if args.order:
        order_file = group_dir / "orderings" / f"{args.order}.json"
        if not order_file.exists():
            logger.error("Ordering file not found: %s", order_file)
            sys.exit(1)
        explicit_task_order = json.load(open(order_file))["order"]
        logger.info("Using explicit task ordering: %s (%d tasks)", args.order, len(explicit_task_order))

    # --task-list selects AND orders the tasks: pass as both `only` (filter) and
    # `task_order` (sequence) so run_group runs exactly this list in this order.
    task_order_seed = args.seed if args.task_order == "random" else None
    results = agent.run_group(
        task_order_seed=task_order_seed,
        task_order=task_list if task_list else explicit_task_order,
        limit=args.limit,
        only=(task_list if task_list
              else ([t.strip() for t in args.only.split(",") if t.strip()] if args.only else None)),
    )
    elapsed = time.time() - start_time

    # --commit-image: checkpoint the container's /workspace NOW — after the agent finished the
    # task-list but before evaluation (which may run post-fix tests that further mutate the
    # workspace) and before teardown. This captures the workspace exactly as the agent left it,
    # which is what a factorial fan-out (Y) run must start from. Docker mode only.
    if args.commit_image and args.sandbox_mode == "docker":
        try:
            sandbox.commit_image(args.commit_image)
        except Exception as e:  # noqa: BLE001 — surface but let the run finish/score
            logger.error("--commit-image failed (%s); factorial fan-out from this checkpoint "
                         "will be unavailable.", e)

    # Export each task's namespaced service state (workspace-acme domain). No-op for DevOps
    # (its executor has no snapshot_export.sh), so this is safe on every run.
    if args.sandbox_mode == "docker":
        try:
            export_service_snapshots(sandbox, group_dir, results)
        except Exception as e:  # noqa: BLE001 — export must never sink a completed run
            logger.warning("Service-state export failed (continuing): %s", e)

    # Everything after execution (save results/config, report, evaluation, metrics, plots).
    # Shared with --resume-from, so a crash in this tail can be re-run without re-executing.
    _finalize_run(args, agent, results, elapsed, run_name, any_evolution,
                  sandbox if args.sandbox_mode == "docker" else None, group_dir)

    # POST-ARM service reset (Fix B, TAC). The pre-task reset in _start_container leaves the stack
    # clean for THIS arm; a post-arm reset leaves it clean AFTER this arm, so the next arm (a separate
    # process) cannot start against this arm's residue even before its own pre-task reset runs. Only
    # the HOST reset matters here — it cleans the shared ownCloud/RocketChat; the in-container
    # control-state reset is per-container and is recreated by the next arm's start. Run AFTER
    # _finalize_run so the state being scored was intact during scoring. No-op when no host reset is
    # configured (DevOps/fintech unaffected). In strict mode a failure fails the run (exit 1) so a
    # dirty stack is surfaced rather than silently carried into the sweep; teardown still happens.
    post_arm_reset_exc = None
    if args.sandbox_mode == "docker" and getattr(args, "service_host_reset_cmd", None):
        logger.info("Running POST-arm host-side service reset")
        try:
            sandbox._run_service_host_reset()
        except Exception as e:  # only raised in strict mode
            post_arm_reset_exc = e

    # Teardown sandbox (after evaluation, since post-fix tests need it)
    sandbox.teardown()

    # Tear down the persistent service stack only if explicitly requested (default: leave up
    # so subsequent runs reuse it — booting it is slow).
    if service_stack is not None:
        service_stack.down()

    if post_arm_reset_exc is not None:
        logger.error("POST-ARM reset failed under --service-reset-strict; failing the run so the "
                     "batch does not continue against an unknown stack state: %s", post_arm_reset_exc)
        sys.exit(1)

    # Final summary
    print(f"\nAll outputs saved to: {agent.cache_dir}/")
    print(f"  results.json        - Full task results with trajectories")
    print(f"  report.json         - Summary report")
    print(f"  config.json         - Run configuration")
    print(f"  trajectory_history.jsonl - Step-by-step trajectory (OAS-compatible)")
    if args.evaluate:
        print(f"  evaluation.json     - Evaluation (LLM judge + test verification)")


if __name__ == "__main__":
    main()
