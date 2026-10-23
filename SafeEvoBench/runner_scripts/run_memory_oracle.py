#!/usr/bin/env python
"""Run a controlled good/bad/agent-authored memory intervention on one pair."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import queue
import shutil
import statistics
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from benchmarks.safeevobench.run_pairs import (  # noqa: E402
    _archive_incomplete_arm,
    _arm_completion_error,
    _target_scores,
    causal_evidence,
    preflight_bedrock,
    target_reuse,
)

LOGGER = logging.getLogger("memory-oracle")
# The two fixed arms; oracle_* arms are discovered per pair from oracle_memories.json.
BASE_ARMS = ("cold", "agent_memory")
IMAGE_BY_GROUP = {
    "devops": "safeevo-devops-v2:latest",
    "fintech": "safeevo-fintech-v2:latest",
    "tac": "safeevo-tac-v2:latest",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_pair(group_dir: Path, pair_id: str) -> dict[str, Any]:
    pairs = _read_json(group_dir / "pairs.json").get("pairs") or []
    matches = [pair for pair in pairs if pair.get("id") == pair_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one pair named {pair_id!r}")
    pair = dict(matches[0])
    sources = pair.get("source")
    pair["sources"] = sources if isinstance(sources, list) else [sources]
    if len(pair["sources"]) != 1:
        raise ValueError("the memory oracle currently requires a single-source pair")
    return pair


def _load_oracle_memories(group_dir: Path, pair: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Load and validate the hand-authored oracle memories for one pair.

    Reads ``<group>/oracle_memories.json`` (the sibling file that keeps pairs.json schema-pure),
    validates its recorded source/target against pairs.json, and returns the ``*_memory`` variant
    dicts ({variant: {title, content}}). The set of variants present here drives the oracle arms;
    the runner adds no memory keys of its own.
    """
    doc = _read_json(group_dir / "oracle_memories.json")
    memories = (doc.get("memories") or {}).get(pair["id"])
    if not isinstance(memories, dict):
        raise ValueError(
            f"oracle_memories.json has no entry for pair {pair['id']!r}"
        )
    for role, key in (("source", pair["sources"][0]), ("target", pair["target"])):
        recorded = memories.get(role)
        if recorded is not None and recorded != key:
            raise ValueError(
                f"{pair['id']}: oracle_memories.json {role}={recorded!r} != pairs.json {key!r}"
            )
    variants = {}
    for key, value in memories.items():
        if not key.endswith("_memory"):
            continue
        variant = key[: -len("_memory")]
        title = (value or {}).get("title")
        content = (value or {}).get("content")
        if not str(title or "").strip() or not str(content or "").strip():
            raise ValueError(f"{pair['id']}/{key}: title and content must both be non-empty")
        variants[variant] = {"title": title, "content": content}
    if not variants:
        raise ValueError(f"{pair['id']}: oracle_memories.json entry has no *_memory variants")
    return variants


def _materialize_oracle_seed(
    memory: dict[str, str], source_id: str, out_dir: Path
) -> Path:
    """Write a one-entry memory.json seed that mirrors what save_memory would have produced.

    The agent's save_memory writes source="orchestrator", importance=3, path="uncategorized",
    tags=[] (agent.py + MemoryEntry defaults); mirroring them keeps the injected memory
    indistinguishable from an agent-authored one. created_in_task carries the source task id so the
    reuse detector attributes any target-task pull to the source (run_pairs.py split("@")[-1]).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        out_dir / "memory.json",
        {
            "next_id": 2,
            "entries": {
                "mem_0001": {
                    "id": "mem_0001",
                    "path": "uncategorized",
                    "title": memory["title"],
                    "content": memory["content"],
                    "location": None,
                    "coordinates": None,
                    "tags": [],
                    "created_at": "2026-08-06T00:00:00",
                    "updated_at": "2026-08-06T00:00:00",
                    "importance": 3,
                    "source": "orchestrator",
                    "created_in_task": source_id,
                    "last_modified_step": None,
                    "mutation_history": [],
                }
            },
        },
    )
    return out_dir


def _contract(
    args: argparse.Namespace,
    pair: dict[str, Any],
    target_arms: tuple[str, ...],
    oracle_seeds: dict[str, Path],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "experiment": "memory_oracle",
        "run_tag": args.run_tag,
        "model": args.model,
        "model_short": args.model_short,
        "judge": args.judge,
        "group": str(Path(args.group).resolve()),
        "pair_id": pair["id"],
        "source": pair["sources"][0],
        "target": pair["target"],
        "config": "memory",
        "planning_enabled": False,
        "memory_prompt_variant": getattr(args, "memory_prompt_variant", "current") or "current",
        "replicates": args.replicates,
        "target_arms": list(target_arms),
        "sandbox_mode": args.sandbox_mode,
        "docker_image": args.docker_image if args.sandbox_mode == "docker" else None,
        "oracle_memories_sha256": _sha256(
            Path(args.group).resolve() / "oracle_memories.json"
        ),
        "oracle_memories": {
            variant: {
                "path": str(seed),
                "sha256": _sha256(seed / "memory.json"),
            }
            for variant, seed in sorted(oracle_seeds.items())
        },
    }


def _initialize_batch(batch_dir: Path, contract: dict[str, Any]) -> None:
    contract_path = batch_dir / "experiment_contract.json"
    if contract_path.exists():
        existing = _read_json(contract_path)
        if existing != contract:
            raise ValueError(
                f"experiment contract mismatch at {contract_path}; use the original "
                "arguments or choose a new --run-tag"
            )
        return
    # `seeds/` is materialized before this call (the contract hashes those seeds); it is our own
    # deterministic output, so it does not count as a pre-existing foreign batch.
    stray = [p for p in batch_dir.iterdir() if p.name != "seeds"] if batch_dir.exists() else []
    if stray:
        raise ValueError(
            f"refusing to use non-empty batch without experiment contract: {batch_dir}"
        )
    batch_dir.mkdir(parents=True, exist_ok=True)
    _write_json(contract_path, contract)


def _command(
    args: argparse.Namespace,
    batch_dir: Path,
    run_name: str,
    task_id: str,
    port: int,
    seed_store: Path | None,
) -> list[str]:
    command = [
        args.python,
        str(REPO_ROOT / "benchmarks" / "safeevobench" / "run.py"),
        "--group",
        str(Path(args.group).resolve()),
        "--model",
        args.model,
        "--run-name",
        run_name,
        "--cache-dir",
        str(batch_dir),
        "--sandbox-mode",
        args.sandbox_mode,
        "--task-list",
        task_id,
        "--no-enable-planning",
        "--enable-memory",
        "--evaluate",
        "--judge",
        args.judge,
    ]
    # Forward a non-default memory-prompt variant (e.g. `generalize`) to run.py. The default
    # ("current") is left implicit so existing batches keep their exact command string.
    # run.py requires MEMORY_MODE=pull for a non-current variant; that is already the default.
    if getattr(args, "memory_prompt_variant", "current") not in (None, "current"):
        command.extend(["--memory-prompt-variant", args.memory_prompt_variant])
    if seed_store is not None:
        command.extend(["--seed-store", str(seed_store)])
    if args.sandbox_mode == "docker":
        command.extend(
            [
                "--docker-image",
                args.docker_image,
                "--docker-memory",
                args.docker_memory,
                "--port",
                str(port),
            ]
        )
    return command


def _run_unit(
    args: argparse.Namespace,
    batch_dir: Path,
    run_name: str,
    task_id: str,
    port: int,
    seed_store: Path | None = None,
) -> Path | None:
    run_dir = batch_dir / run_name
    completion_error = _arm_completion_error(
        run_dir,
        model=args.model,
        judge=args.judge,
        task_list=[task_id],
        sandbox_mode=args.sandbox_mode,
        enable_planning=False,
        reset_workspace=False,
        memory_prompt_variant=getattr(args, "memory_prompt_variant", "current") or "current",
    )
    if completion_error is None:
        LOGGER.info("reuse complete unit: %s", run_name)
        return run_dir
    if run_dir.exists():
        archived = _archive_incomplete_arm(batch_dir, run_name, completion_error)
        LOGGER.warning("archived incomplete unit at %s", archived)

    command = _command(args, batch_dir, run_name, task_id, port, seed_store)
    if args.dry_run:
        print(" ".join(subprocess.list2cmdline([item]) for item in command))
        return None
    LOGGER.info("start unit: %s", run_name)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=args.unit_timeout,
        )
    except subprocess.TimeoutExpired:
        LOGGER.error("unit timed out after %ss: %s", args.unit_timeout, run_name)
        return None
    if result.returncode:
        tail = "\n".join(
            ((result.stderr or "") + "\n" + (result.stdout or "")).splitlines()[-12:]
        )
        LOGGER.error("unit failed (%d): %s\n%s", result.returncode, run_name, tail)
        return None
    error = _arm_completion_error(
        run_dir,
        model=args.model,
        judge=args.judge,
        task_list=[task_id],
        sandbox_mode=args.sandbox_mode,
        enable_planning=False,
        reset_workspace=False,
        memory_prompt_variant=getattr(args, "memory_prompt_variant", "current") or "current",
    )
    if error:
        LOGGER.error("unit finished without valid scored output: %s: %s", run_name, error)
        return None
    LOGGER.info("done unit: %s", run_name)
    return run_dir


def _stash_agent_memory(source_dir: Path, stash_dir: Path, source: str) -> Path:
    memory_path = source_dir / "memory.json"
    if not memory_path.is_file():
        # The agent completed the source task without ever calling save_memory. That is a
        # legitimate outcome (common on benign sources), not an error: the agent_memory arm then
        # starts from an empty store - memory enabled but nothing seeded. Stash an empty store.
        LOGGER.info("source run wrote no memory store; agent_memory arm starts empty: %s", source_dir)
        document = {"next_id": 1, "entries": {}}
    else:
        document = _read_json(memory_path)
    entries = document.get("entries") or {}
    source_entries = {
        entry_id: entry
        for entry_id, entry in entries.items()
        if (entry.get("created_in_task") or "").split("@")[-1] == source
    }
    stash_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        stash_dir / "memory.json",
        {
            "next_id": max(1, int(document.get("next_id") or 1)),
            "entries": source_entries,
        },
    )
    return stash_dir


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _summarize(
    batch_dir: Path,
    contract: dict[str, Any],
    pair: dict[str, Any],
) -> dict[str, Any]:
    target = pair["target"]
    source = pair["sources"][0]
    target_arms = tuple(contract["target_arms"])
    run_rows = []
    for replicate in range(int(contract["replicates"])):
        for arm in target_arms:
            run_dir = batch_dir / f"r{replicate}" / arm
            utility, harm = _target_scores(run_dir if run_dir.is_dir() else None, target)
            reuse = (
                target_reuse(run_dir, [source], target)
                if run_dir.is_dir()
                else {}
            )
            run_rows.append(
                {
                    "replicate": replicate,
                    "arm": arm,
                    "utility": utility,
                    "harm": harm,
                    "safety": 1.0 - harm if harm is not None else None,
                    "memory_pulls": int(reuse.get("content_pull") or 0),
                    "memory_discovery": int(reuse.get("discovery") or 0),
                    "causal_evidence": (
                        causal_evidence(run_dir, [source], target)
                        if run_dir.is_dir()
                        else "missing"
                    ),
                    "run_dir": str(run_dir),
                }
            )

    cold_by_rep = {
        row["replicate"]: row
        for row in run_rows
        if row["arm"] == "cold" and row["utility"] is not None
    }
    arm_summaries = {}
    for arm in target_arms:
        rows = [row for row in run_rows if row["arm"] == arm and row["utility"] is not None]
        utility = [float(row["utility"]) for row in rows]
        safety = [float(row["safety"]) for row in rows]
        paired_du = []
        paired_ds = []
        for row in rows:
            cold = cold_by_rep.get(row["replicate"])
            if cold is not None:
                paired_du.append(float(row["utility"]) - float(cold["utility"]))
                paired_ds.append(float(row["safety"]) - float(cold["safety"]))
        arm_summaries[arm] = {
            "n": len(rows),
            "mean_utility": _mean(utility),
            "mean_safety": _mean(safety),
            "mean_delta_utility_vs_cold": _mean(paired_du) if arm != "cold" else 0.0,
            "mean_delta_safety_vs_cold": _mean(paired_ds) if arm != "cold" else 0.0,
            "memory_pulled_replicates": sum(row["memory_pulls"] > 0 for row in rows),
            "causal_evidence": dict(
                (label, sum(row["causal_evidence"] == label for row in rows))
                for label in ("used", "pulled_not_used", "no_pull", "unknown")
            ),
        }

    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "contract": contract,
        "arms": arm_summaries,
        "runs": run_rows,
    }
    _write_json(batch_dir / "summary.json", summary)
    with (batch_dir / "runs.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(run_rows[0]))
        writer.writeheader()
        writer.writerows(run_rows)

    lines = [
        f"# Memory oracle experiment: {pair['id']}",
        "",
        f"- Source: `{source}`",
        f"- Target: `{target}`",
        f"- Model: `{contract['model_short']}`",
        f"- Replicates: {contract['replicates']}",
        "",
        "| Arm | n | Mean safety | dSafety vs cold | Mean utility | dUtility vs cold | Memory pulled |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in target_arms:
        row = arm_summaries[arm]
        fmt = lambda value: "n/a" if value is None else f"{value:+.3f}"
        lines.append(
            f"| {arm} | {row['n']} | {fmt(row['mean_safety'])} | "
            f"{fmt(row['mean_delta_safety_vs_cold'])} | {fmt(row['mean_utility'])} | "
            f"{fmt(row['mean_delta_utility_vs_cold'])} | "
            f"{row['memory_pulled_replicates']}/{row['n']} |"
        )
    (batch_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def run(args: argparse.Namespace) -> Path:
    group_dir = Path(args.group).resolve()
    pair = _load_pair(group_dir, args.pair)
    source_id = pair["sources"][0]
    variants = _load_oracle_memories(group_dir, pair)

    batch_dir = (
        Path(args.cache_dir).resolve()
        / f"{args.pair}_{args.model_short}_memory_oracle_{args.run_tag}"
    )
    # Materialize one seed store per authored variant; the set of variants drives the oracle arms.
    oracle_seeds = {
        variant: _materialize_oracle_seed(
            memory, source_id, batch_dir / "seeds" / f"oracle_{variant}"
        )
        for variant, memory in sorted(variants.items())
    }
    target_arms = BASE_ARMS + tuple(f"oracle_{variant}" for variant in sorted(variants))
    contract = _contract(args, pair, target_arms, oracle_seeds)
    _initialize_batch(batch_dir, contract)

    if args.sandbox_mode == "docker" and not args.no_preflight and not args.dry_run:
        preflight_bedrock([args.model, args.judge])

    ports: queue.Queue[int] = queue.Queue()
    for offset in range(max(1, args.concurrency)):
        ports.put(args.port + offset)

    def execute(
        run_name: str, task_id: str, seed_store: Path | None = None
    ) -> Path | None:
        port = ports.get()
        try:
            return _run_unit(
                args, batch_dir, run_name, task_id, port, seed_store=seed_store
            )
        finally:
            ports.put(port)

    source_dirs: dict[int, Path | None] = {}
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = {
            pool.submit(
                execute,
                f"r{replicate}/source",
                pair["sources"][0],
            ): replicate
            for replicate in range(args.replicates)
        }
        for future in as_completed(futures):
            source_dirs[futures[future]] = future.result()

    target_jobs = []
    for replicate in range(args.replicates):
        source_dir = source_dirs.get(replicate)
        agent_seed = (
            batch_dir / "seeds" / f"agent_r{replicate}"
            if args.dry_run
            else None
        )
        if source_dir is not None:
            agent_seed = _stash_agent_memory(
                source_dir,
                batch_dir / "seeds" / f"agent_r{replicate}",
                source_id,
            )
        target_jobs.append((f"r{replicate}/cold", None))
        target_jobs.append((f"r{replicate}/agent_memory", agent_seed))
        for variant, seed in sorted(oracle_seeds.items()):
            target_jobs.append((f"r{replicate}/oracle_{variant}", seed))

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        futures = [
            pool.submit(execute, run_name, pair["target"], seed)
            for run_name, seed in target_jobs
        ]
        for future in as_completed(futures):
            future.result()

    if not args.dry_run:
        summary = _summarize(batch_dir, contract, pair)
        print(f"Report: {batch_dir / 'report.md'}")
        print(
            "Complete target arms: "
            f"{sum(row['n'] for row in summary['arms'].values())}/"
            f"{len(target_arms) * args.replicates}"
        )
    else:
        print(f"Dry run contract: {batch_dir / 'experiment_contract.json'}")
    return batch_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", default=str(REPO_ROOT / "SafeEvoBench" / "devops"))
    parser.add_argument("--pair", default="devops_DD02")
    parser.add_argument("--model", default="moonshotai.kimi-k2.5")
    parser.add_argument("--model-short", default="kimi-k2.5")
    parser.add_argument("--judge", default="us.anthropic.claude-sonnet-4-6")
    parser.add_argument("--replicates", type=int, default=3)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--port", type=int, default=7200)
    parser.add_argument("--unit-timeout", type=int, default=1800)
    parser.add_argument(
        "--python",
        default=os.environ.get("PY", sys.executable),
        help="Python interpreter used for run.py subprocesses.",
    )
    parser.add_argument("--sandbox-mode", choices=("docker", "mock"), default="docker")
    parser.add_argument(
        "--docker-image",
        default=None,
        help="Docker image; defaults to the image for --group's domain (IMAGE_BY_GROUP).",
    )
    parser.add_argument("--docker-memory", default="2g")
    parser.add_argument(
        "--memory-prompt-variant",
        default="current",
        help=(
            "Conditional voluntary-memory prompt supplement forwarded to run.py "
            "(current|generalize|generalize_urgent|generalize_urgent_trust). "
            "Non-current values require MEMORY_MODE=pull, which is the default."
        ),
    )
    parser.add_argument("--cache-dir", default=".safeevo_cache/oracle_memory")
    parser.add_argument("--run-tag", default="pilot_01")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    args = parser.parse_args()
    if args.replicates < 1:
        parser.error("--replicates must be >= 1")
    if args.concurrency < 1:
        parser.error("--concurrency must be >= 1")
    if args.docker_image is None:
        domain = Path(args.group).resolve().name
        if domain not in IMAGE_BY_GROUP:
            parser.error(
                f"no default docker image for group {domain!r}; pass --docker-image "
                f"(known: {sorted(IMAGE_BY_GROUP)})"
            )
        args.docker_image = IMAGE_BY_GROUP[domain]
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
