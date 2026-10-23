#!/usr/bin/env python3
"""Shared, standard-library helpers for SafeEvoBench calibration analyses."""

from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
from pathlib import Path
from typing import Any, Iterable, Sequence


class CalibrationError(RuntimeError):
    """Raised when calibration inputs cannot support the requested analysis."""


def stable_seed(seed: int, *parts: object) -> int:
    raw = json.dumps([seed, *parts], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def resolve_collective_inputs(raw_paths: Sequence[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in raw_paths:
        path = Path(raw).expanduser()
        if path.is_file():
            found.add(path.resolve())
            continue
        if path.is_dir():
            direct = path / "collective_results.json"
            if direct.is_file():
                found.add(direct.resolve())
            else:
                found.update(p.resolve() for p in path.glob("*/collective_results.json"))
            continue
        raise CalibrationError(f"input does not exist: {raw}")
    if not found:
        raise CalibrationError("input selection contains no collective_results.json files")
    return sorted(found)


def _domain(document: dict[str, Any], path: Path) -> str:
    group = str(document.get("group") or "")
    if group:
        return Path(group.rstrip("/")).name
    name = path.parent.name
    return name.split("_", 1)[0] if "_" in name else name


def load_study_documents(
    raw_paths: Sequence[str],
    *,
    expected_phase: str = "pilot",
    allow_unphased: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load collective summaries and enforce one independent study identity."""
    documents: list[dict[str, Any]] = []
    phases: set[str] = set()
    study_ids: set[str] = set()
    freeze_ids: set[str] = set()
    inputs = resolve_collective_inputs(raw_paths)

    for path in inputs:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"cannot read {path}: {exc}") from exc
        if not isinstance(document, dict):
            raise CalibrationError(f"{path}: root must be an object")

        phase = document.get("study_phase")
        study_id = document.get("study_id")
        freeze_id = document.get("freeze_id")
        provisional = False
        if not all(isinstance(v, str) and v for v in (phase, study_id, freeze_id)):
            if not allow_unphased:
                raise CalibrationError(
                    f"{path}: official calibration input requires non-empty study_phase, "
                    "study_id, and freeze_id; use --allow-unphased only for provisional "
                    "analysis of legacy runs"
                )
            phase = "legacy-unphased"
            study_id = f"legacy-{file_sha256(path)[:12]}"
            freeze_id = "unknown"
            provisional = True
        elif phase != expected_phase:
            raise CalibrationError(
                f"{path}: study_phase is {phase!r}, expected {expected_phase!r}"
            )

        phases.add(phase)
        if not provisional:
            study_ids.add(study_id)
            freeze_ids.add(freeze_id)
        documents.append(
            {
                "path": path,
                "sha256": file_sha256(path),
                "domain": _domain(document, path),
                "phase": phase,
                "study_id": study_id,
                "freeze_id": freeze_id,
                "provisional": provisional,
                "document": document,
            }
        )

    if len(study_ids) > 1:
        raise CalibrationError(f"inputs mix study IDs: {sorted(study_ids)}")
    if len(freeze_ids) > 1:
        raise CalibrationError(f"inputs mix freeze IDs: {sorted(freeze_ids)}")
    official = not any(item["provisional"] for item in documents)
    metadata = {
        "phase": expected_phase if official else "legacy-unphased",
        "study_id": next(iter(study_ids), "legacy-mixed"),
        "freeze_id": next(iter(freeze_ids), "unknown"),
        "official_inputs": official,
        "input_files": [
            {"path": str(item["path"]), "sha256": item["sha256"]}
            for item in documents
        ],
    }
    metadata["input_digest"] = canonical_sha256(metadata["input_files"])
    return documents, metadata


def axis_runs(block: Any, axis: str) -> list[float]:
    value = (block or {}).get(axis) if isinstance(block, dict) else None
    if isinstance(value, dict):
        raw = value.get("runs")
        values = raw if isinstance(raw, list) else [value.get("mean")]
    else:
        values = [value]
    clean: list[float] = []
    for item in values:
        if item is None:
            continue
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise CalibrationError(f"{axis} score is not numeric: {item!r}")
        score = float(item)
        if not 0.0 <= score <= 1.0:
            raise CalibrationError(f"{axis} score is outside [0, 1]: {score}")
        clean.append(score)
    return clean


def mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def sample_sd(values: Sequence[float]) -> float | None:
    return statistics.stdev(values) if len(values) > 1 else None


def percentile(values: Sequence[float], probability: float) -> float:
    if not values:
        raise CalibrationError("cannot take a percentile of an empty sequence")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = min(max(probability, 0.0), 1.0) * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def bootstrap_mean_interval(
    values: Sequence[float],
    *,
    confidence: float,
    samples: int,
    seed: int,
) -> list[float] | None:
    if not values:
        return None
    if len(values) == 1 or samples <= 0:
        value = float(values[0])
        return [value, value]
    rng = random.Random(seed)
    size = len(values)
    means = [
        statistics.fmean(values[rng.randrange(size)] for _ in range(size))
        for _ in range(samples)
    ]
    tail = (1.0 - confidence) / 2.0
    return [percentile(means, tail), percentile(means, 1.0 - tail)]


def pooled_within_cell_sd(groups: Iterable[Sequence[float]]) -> float | None:
    numerator = 0.0
    denominator = 0
    for values in groups:
        if len(values) < 2:
            continue
        center = statistics.fmean(values)
        numerator += sum((value - center) ** 2 for value in values)
        denominator += len(values) - 1
    return math.sqrt(numerator / denominator) if denominator else None


def clipped_gaussian_mean(
    rng: random.Random, center: float, sd: float, count: int
) -> float:
    if count < 1:
        raise CalibrationError("replicate count must be positive")
    if sd <= 0:
        return min(1.0, max(0.0, center))
    return statistics.fmean(
        min(1.0, max(0.0, rng.gauss(center, sd))) for _ in range(count)
    )

