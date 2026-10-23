"""Data loading utilities for the SafeEvoBench analysis notebook.

The cache contains historical ``pairs.json`` summaries and current
``collective_results.json`` summaries, plus both scalar and multi-run score
blocks. Current summaries report higher-is-better safety and default to the
workspace-reset ``store_only`` treatment arm. This module normalizes both
generations into the historical harm-oriented row schema.
It deliberately depends only on the Python standard library.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

_TIMESTAMP_RE = re.compile(r"^\d{8}_\d{6}$")
_STORE_FILES = {
    "memory": "memory.json",
    "skills": "skills.json",
    "subagents": "subagents.json",
}


def short_model(model: str | None) -> str:
    """Return a readable, stable label for a model ID."""
    if not model:
        return "unknown"
    parts = model.split(".")
    if len(parts) > 1 and parts[-1].replace("-", "").isdigit():
        return ".".join(parts[-2:])
    return parts[-1].removesuffix("-v1:0")


def _axis_runs(block: dict[str, Any], axis: str) -> list[float | None]:
    """Read one axis from either the scalar or replicate summary shape."""
    value = (block or {}).get(axis)
    invert = False
    if axis == "harm" and value is None and "safety" in (block or {}):
        value = block.get("safety")
        invert = True
    if isinstance(value, dict):
        runs = value.get("runs")
        if isinstance(runs, list):
            values = runs
        else:
            values = [value.get("mean")]
    else:
        values = [value]
    if invert:
        return [1.0 - item if item is not None else None for item in values]
    return values


def _treatment_arm(pair: dict[str, Any]) -> str:
    """Choose the historical natural arm or current default store-only arm."""
    if any(value is not None for value in _axis_runs(pair.get("natural", {}), "utility")):
        return "natural"
    if any(value is not None for value in _axis_runs(pair.get("store_only", {}), "utility")):
        return "store_only"
    return "natural"


def _saved_delta(pair: dict[str, Any], arm: str, axis: str) -> float | None:
    block_name = "delta_store_only" if arm == "store_only" else "delta"
    block = pair.get(block_name, {})
    value = block.get(axis)
    if axis == "harm" and value is None and block.get("safety") is not None:
        return -block["safety"]
    return value


def _mean(values: Iterable[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return sum(clean) / len(clean) if clean else None


def _definition_id(group: str, quadrant: str, sources: Sequence[str], target: str) -> str:
    raw = json.dumps([group, quadrant, list(sources), target], separators=(",", ":"))
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _parse_started_at(tag: Any) -> datetime | None:
    text = str(tag or "")
    if not _TIMESTAMP_RE.fullmatch(text):
        return None
    return datetime.strptime(text, "%Y%m%d_%H%M%S")


def _resolve_arm_path(raw: Any, batch_path: Path) -> Path | None:
    if not raw:
        return None
    path = Path(str(raw))
    if path.exists():
        return path
    if batch_path.name in path.parts:
        batch_index = len(path.parts) - 1 - path.parts[::-1].index(batch_path.name)
        relocated = batch_path.joinpath(*path.parts[batch_index + 1 :])
        if relocated.exists():
            return relocated
    candidate = batch_path / path.name
    return candidate if candidate.exists() else path


def _arm_paths(pair: dict[str, Any], arm: str, batch_path: Path) -> list[Path | None]:
    plural = pair.get(f"{arm}_runs")
    if isinstance(plural, list):
        return [_resolve_arm_path(path, batch_path) for path in plural]
    return [_resolve_arm_path(pair.get(f"{arm}_run"), batch_path)]


class _ArmScanner:
    """Cached reader for the small evaluation/provenance files in arm directories."""

    def __init__(self) -> None:
        self._json: dict[Path, dict[str, Any]] = {}
        self._events: dict[Path, list[dict[str, Any]]] = {}

    def json_file(self, path: Path) -> dict[str, Any]:
        if path not in self._json:
            try:
                self._json[path] = json.loads(path.read_text())
            except (OSError, json.JSONDecodeError):
                self._json[path] = {}
        return self._json[path]

    def events(self, path: Path) -> list[dict[str, Any]]:
        if path not in self._events:
            parsed = []
            try:
                for line in path.read_text().splitlines():
                    if not line.strip():
                        continue
                    parsed.append(json.loads(line))
            except (OSError, json.JSONDecodeError):
                parsed = []
            self._events[path] = parsed
        return self._events[path]

    def _source_artifacts(self, arm_path: Path, sources: set[str]) -> dict[str, int]:
        counts = {}
        for mechanism, filename in _STORE_FILES.items():
            entries = self.json_file(arm_path / filename).get("entries", {})
            counts[mechanism] = sum(
                1
                for entry in entries.values()
                if (entry.get("created_in_task") or "").split("@")[-1] in sources
            )
        return counts

    def scan(
        self,
        arm_path: Path | None,
        target: str,
        sources: Sequence[str],
        *,
        natural: bool,
    ) -> dict[str, Any]:
        empty = {
            "arm_exists": False,
            "judge_model": None,
            "target_steps": None,
            "target_completed": None,
            "source_steps": None,
            "source_memory_artifacts": None,
            "source_skill_artifacts": None,
            "source_subagent_artifacts": None,
            "source_artifacts": None,
            "source_evolve_calls": None,
            "source_evolution_events": None,
            "pull_count": None,
            "push_count": None,
            "discovery_count": None,
            "pulled_source": None,
            "pushed_source": None,
            "source_exposed": None,
            "pull_tools": (),
            "push_tools": (),
        }
        if arm_path is None or not arm_path.is_dir():
            return empty

        evaluation = self.json_file(arm_path / "evaluation.json")
        task_eval = evaluation.get("tasks", {}).get(target, {})
        judge_model = (
            task_eval.get("harm", {}).get("model")
            or task_eval.get("utility", {}).get("model")
        )
        per_task = evaluation.get("evolution_metrics", {}).get("per_task", {})
        target_metrics = per_task.get(target, {})
        source_metrics = [per_task.get(source, {}) for source in sources]
        detail = {
            **empty,
            "arm_exists": True,
            "judge_model": judge_model,
            "target_steps": target_metrics.get("steps", task_eval.get("steps")),
            "target_completed": target_metrics.get("completed", task_eval.get("completed")),
            "source_steps": sum(m.get("steps", 0) or 0 for m in source_metrics) if natural else 0,
        }
        if not natural:
            return detail

        source_set = set(sources)
        artifacts = self._source_artifacts(arm_path, source_set)
        evolve_calls = sum(m.get("evolve_harness", 0) or 0 for m in source_metrics)
        events = self.events(arm_path / "transfer_events.jsonl")
        pulls = []
        pushes = []
        discoveries = []
        for event in events:
            if event.get("current_task") != target:
                continue
            source_match = any(source in source_set for source in (event.get("source_tasks") or []))
            artifact_match = any(
                (
                    artifact.get("origin_task")
                    or (artifact.get("created_in_task") or "").split("@")[-1]
                )
                in source_set
                for artifact in event.get("artifacts", [])
            )
            if not (source_match or artifact_match):
                continue
            if event.get("kind") == "content_pull":
                pulls.append(event)
            elif event.get("kind") == "content_push":
                pushes.append(event)
            elif event.get("kind") == "discovery":
                discoveries.append(event)

        source_artifacts = sum(artifacts.values())
        return {
            **detail,
            "source_memory_artifacts": artifacts["memory"],
            "source_skill_artifacts": artifacts["skills"],
            "source_subagent_artifacts": artifacts["subagents"],
            "source_artifacts": source_artifacts,
            "source_evolve_calls": evolve_calls,
            "source_evolution_events": source_artifacts + evolve_calls,
            "pull_count": len(pulls),
            "push_count": len(pushes),
            "discovery_count": len(discoveries),
            "pulled_source": bool(pulls),
            "pushed_source": bool(pushes),
            "source_exposed": bool(pulls or pushes),
            "pull_tools": tuple(sorted({event.get("tool", "unknown") for event in pulls})),
            "push_tools": tuple(sorted({event.get("tool", "unknown") for event in pushes})),
        }


def discover_summaries(cache_dir: str | Path) -> list[Path]:
    """Find pair summaries without traversing large trajectory/result files."""
    root = Path(cache_dir)
    paths = set(root.glob("seb_*/pairs.json"))
    paths.update(root.glob("*/collective_results.json"))
    direct = root / "collective_results.json"
    if direct.is_file():
        paths.add(direct)
    return sorted(paths)


def load_results(
    cache_dir: str | Path = ".safeevo_cache",
    *,
    scan_arm_details: bool = True,
    full_sweep_min_pairs: int = 50,
) -> dict[str, list[dict[str, Any]] | list[str]]:
    """Load all pair summaries into batch-level and replicate-level records.

    ``runs`` contains one row per pair replicate. A same-index cold/treatment
    difference is included for diagnostics. Aggregate analyses should cluster
    by target task because targets recur across independently sampled edges.
    """
    root = Path(cache_dir)
    scanner = _ArmScanner()
    batches: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    issues: list[str] = []

    summary_paths = discover_summaries(root)
    summary_dirs = {path.parent.resolve() for path in summary_paths}
    candidate_dirs = [
        path
        for path in root.iterdir()
        if path.is_dir()
        and (path.name.startswith("seb_") or (path / "batch_contract.json").is_file())
    ] if root.is_dir() else []
    incomplete_dirs = sorted(
        path.name for path in candidate_dirs if path.resolve() not in summary_dirs
    )
    if incomplete_dirs:
        issues.append(
            f"{len(incomplete_dirs)} batch directories have no pair summary and were excluded: "
            + ", ".join(incomplete_dirs[:5])
            + (" ..." if len(incomplete_dirs) > 5 else "")
        )

    for summary_path in summary_paths:
        try:
            document = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"Could not read {summary_path}: {exc}")
            continue

        pair_docs = document.get("pairs") or []
        batch_path = summary_path.parent
        batch_id = batch_path.name
        raw_group = str(document.get("group") or "unknown")
        group = Path(raw_group).name if raw_group != "unknown" else raw_group
        model = str(document.get("model") or "unknown")
        config = str(document.get("config") or "unknown")
        tag = str(document.get("timestamp") or "")
        definitions = [
            _definition_id(
                group,
                str(pair.get("quadrant") or "unknown"),
                tuple(pair.get("sources") or ()),
                str(pair.get("target") or "unknown"),
            )
            for pair in pair_docs
        ]
        definition_set_id = hashlib.sha1("|".join(sorted(definitions)).encode()).hexdigest()[:12]
        batch = {
            "batch_id": batch_id,
            "batch_path": str(batch_path),
            "summary_path": str(summary_path),
            "group": group,
            "model": model,
            "model_short": short_model(model),
            "config": config,
            "tag": tag,
            "started_at": _parse_started_at(tag),
            "is_dated": _parse_started_at(tag) is not None,
            "n_pairs": len(pair_docs),
            "cohort": (
                "sweep"
                if len(pair_docs)
                >= min(full_sweep_min_pairs, {"devops": 48, "fintech": 40}.get(group, full_sweep_min_pairs))
                else "focused"
            ),
            "definition_set_id": definition_set_id,
        }
        batches.append(batch)

        for pair in pair_docs:
            pair_id = str(pair.get("pair_id") or "unknown")
            quadrant = str(pair.get("quadrant") or "unknown")
            sources = tuple(pair.get("sources") or ())
            target = str(pair.get("target") or "unknown")
            edge_id = f"{'+'.join(sources)} -> {target}"
            definition_id = _definition_id(group, quadrant, sources, target)
            treatment_arm = _treatment_arm(pair)
            treatment = pair.get(treatment_arm, {})
            cold_utility = _axis_runs(pair.get("cold", {}), "utility")
            cold_harm = _axis_runs(pair.get("cold", {}), "harm")
            natural_utility = _axis_runs(treatment, "utility")
            natural_harm = _axis_runs(treatment, "harm")
            cold_paths = _arm_paths(pair, "cold", batch_path)
            natural_paths = _arm_paths(pair, treatment_arm, batch_path)
            replicate_count = max(
                len(cold_utility),
                len(cold_harm),
                len(natural_utility),
                len(natural_harm),
                len(cold_paths),
                len(natural_paths),
            )

            computed_du = _mean(natural_utility)
            computed_cu = _mean(cold_utility)
            computed_dh = _mean(natural_harm)
            computed_ch = _mean(cold_harm)
            expected_du = (
                computed_du - computed_cu
                if computed_du is not None and computed_cu is not None
                else None
            )
            expected_dh = (
                computed_dh - computed_ch
                if computed_dh is not None and computed_ch is not None
                else None
            )
            for axis, expected in (("utility", expected_du), ("harm", expected_dh)):
                saved = _saved_delta(pair, treatment_arm, axis)
                if (
                    saved is not None
                    and expected is not None
                    and not math.isclose(saved, expected, abs_tol=2e-4)
                ):
                    issues.append(
                        f"{batch_id}/{pair_id}: saved delta.{axis}={saved} "
                        f"but scores imply {expected:.4f}"
                    )

            def at(values: Sequence[Any], index: int) -> Any:
                return values[index] if index < len(values) else None

            for replicate in range(replicate_count):
                cold_path = at(cold_paths, replicate)
                natural_path = at(natural_paths, replicate)
                cold_detail = (
                    scanner.scan(cold_path, target, sources, natural=False)
                    if scan_arm_details
                    else {}
                )
                natural_detail = (
                    scanner.scan(natural_path, target, sources, natural=True)
                    if scan_arm_details
                    else {}
                )
                cu = at(cold_utility, replicate)
                ch = at(cold_harm, replicate)
                nu = at(natural_utility, replicate)
                nh = at(natural_harm, replicate)
                source_evolution = pair.get("source_evolution", {})
                target_reuse = pair.get("target_reuse", {})
                source_evolved = (
                    (natural_detail.get("source_evolution_events") or 0) > 0
                    if scan_arm_details
                    else None
                )
                pulled_source = natural_detail.get("pulled_source") if scan_arm_details else None
                pushed_source = natural_detail.get("pushed_source") if scan_arm_details else None
                source_exposed = natural_detail.get("source_exposed") if scan_arm_details else None
                ambient_evolution = (
                    (natural_detail.get("source_evolve_calls") or 0) > 0
                    if scan_arm_details
                    else None
                )
                cold_steps = cold_detail.get("target_steps") if scan_arm_details else None
                evolved_steps = natural_detail.get("target_steps") if scan_arm_details else None
                runs.append(
                    {
                        **batch,
                        "pair_id": pair_id,
                        "quadrant": quadrant,
                        "sources": sources,
                        "target": target,
                        "edge_id": edge_id,
                        "definition_id": definition_id,
                        "treatment_arm": treatment_arm,
                        "replicate": replicate,
                        "cold_utility": cu,
                        "cold_harm": ch,
                        "evolved_utility": nu,
                        "evolved_harm": nh,
                        "delta_utility": nu - cu if nu is not None and cu is not None else None,
                        "delta_harm": nh - ch if nh is not None and ch is not None else None,
                        "cold_steps": cold_steps,
                        "evolved_steps": evolved_steps,
                        "delta_steps": (
                            evolved_steps - cold_steps
                            if evolved_steps is not None and cold_steps is not None
                            else None
                        ),
                        "summary_delta_utility": _saved_delta(
                            pair, treatment_arm, "utility"
                        ),
                        "summary_delta_harm": _saved_delta(pair, treatment_arm, "harm"),
                        "cold_run": str(cold_path) if cold_path else None,
                        "natural_run": str(natural_path) if natural_path else None,
                        # Summary provenance describes rep0 only. Keep that limitation explicit.
                        "summary_source_artifacts": (
                            source_evolution.get("total") if replicate == 0 else None
                        ),
                        "summary_content_pulls": (
                            target_reuse.get("content_pull") if replicate == 0 else None
                        ),
                        "summary_content_pushes": (
                            target_reuse.get("content_push") if replicate == 0 else None
                        ),
                        "summary_discoveries": (
                            target_reuse.get("discovery") if replicate == 0 else None
                        ),
                        **{f"cold_{key}": value for key, value in cold_detail.items()},
                        **{f"natural_{key}": value for key, value in natural_detail.items()},
                        "source_evolved": source_evolved,
                        "pulled_source": pulled_source,
                        "pushed_source": pushed_source,
                        "source_exposed": source_exposed,
                        "ambient_evolution": ambient_evolution,
                        "transfer_observed": (
                            bool(source_exposed or ambient_evolution)
                            if scan_arm_details
                            else None
                        ),
                    }
                )

    max_by_group = defaultdict(int)
    for batch in batches:
        max_by_group[batch["group"]] = max(max_by_group[batch["group"]], batch["n_pairs"])
    for batch in batches:
        batch["largest_batch_in_group"] = batch["n_pairs"] == max_by_group[batch["group"]]
    for row in runs:
        row["largest_batch_in_group"] = row["n_pairs"] == max_by_group[row["group"]]

    return {"batches": batches, "runs": runs, "issues": issues}


def data_audit(
    batches: Sequence[dict[str, Any]], runs: Sequence[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return compact audit findings suitable for display in a notebook."""
    findings: list[dict[str, Any]] = []
    missing_scores = sum(
        any(row.get(field) is None for field in ("cold_utility", "cold_harm", "evolved_utility", "evolved_harm"))
        for row in runs
    )
    out_of_bounds = sum(
        value is not None and not 0 <= value <= 1
        for row in runs
        for value in (
            row.get("cold_utility"),
            row.get("cold_harm"),
            row.get("evolved_utility"),
            row.get("evolved_harm"),
        )
    )
    judges = Counter(row.get("natural_judge_model") for row in runs if row.get("natural_judge_model"))
    pair_definitions: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in runs:
        pair_definitions[(row["group"], row["pair_id"])].add(row["definition_id"])
    collisions = sum(len(definitions) > 1 for definitions in pair_definitions.values())
    findings.extend(
        [
            {"check": "summary batches", "value": len(batches), "status": "info"},
            {"check": "replicate-level edge rows", "value": len(runs), "status": "info"},
            {
                "check": "rows with any missing score",
                "value": missing_scores,
                "status": "ok" if missing_scores == 0 else "review",
            },
            {
                "check": "scores outside [0, 1]",
                "value": out_of_bounds,
                "status": "ok" if out_of_bounds == 0 else "review",
            },
            {
                "check": "judge models",
                "value": ", ".join(f"{short_model(model)} ({count})" for model, count in judges.items())
                or "not scanned",
                "status": "ok" if len(judges) <= 1 else "review",
            },
            {
                "check": "group/pair IDs with multiple definitions",
                "value": collisions,
                "status": "review" if collisions else "ok",
            },
            {
                "check": "named/focused batches",
                "value": sum(batch["cohort"] == "focused" for batch in batches),
                "status": "info",
            },
        ]
    )
    return findings


def write_csv(path: str | Path, rows: Sequence[dict[str, Any]]) -> None:
    """Write heterogeneous normalized records, JSON-encoding compound values."""
    if not rows:
        return
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = sorted({key for row in rows for key in row})

    def cell(value: Any) -> Any:
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, (tuple, list, dict)):
            return json.dumps(value)
        return value

    with destination.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in fields})
