#!/usr/bin/env python3
"""Simulate confirmatory replication from independent SafeEvoBench pair pilots."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from SafeEvoBench.qa.calibration_common import (  # noqa: E402
    CalibrationError,
    axis_runs,
    canonical_sha256,
    clipped_gaussian_mean,
    load_study_documents,
    mean,
    percentile,
    pooled_within_cell_sd,
    sample_sd,
    stable_seed,
    write_json,
)


def _parse_number_list(raw: str, cast: type) -> list[Any]:
    try:
        values = [cast(item.strip()) for item in raw.split(",") if item.strip()]
    except ValueError as exc:
        raise CalibrationError(f"invalid comma-separated list: {raw}") from exc
    if not values:
        raise CalibrationError("comma-separated list cannot be empty")
    return values


def _pair_metadata(bank_root: Path, domain: str) -> dict[str, dict[str, Any]]:
    path = bank_root / domain / "pairs.json"
    try:
        pairs = json.loads(path.read_text(encoding="utf-8")).get("pairs", [])
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot read pair metadata from {path}: {exc}") from exc
    return {pair["id"]: pair for pair in pairs if isinstance(pair.get("id"), str)}


def _run_refs(
    summary_path: Path,
    pair_id: str,
    pair: dict[str, Any],
    arm: str,
    count: int,
) -> list[str]:
    plural = pair.get(f"{arm}_runs")
    if isinstance(plural, list) and len(plural) >= count:
        raw = plural[:count]
    else:
        singular = pair.get(f"{arm}_run")
        raw = [singular] if count == 1 and singular else []
    refs = []
    for index in range(count):
        value = raw[index] if index < len(raw) else None
        if value:
            path = Path(str(value))
            if not path.is_absolute():
                candidate = summary_path.parent / path
                path = candidate if candidate.exists() else path
            ref = str(path.resolve()) if path.exists() else str(path)
        else:
            ref = str(
                (summary_path.parent / pair_id / arm / f"r{index}").resolve()
            )
        refs.append(ref)
    return refs


def load_pair_observations(
    inputs: Sequence[str],
    *,
    bank_root: Path,
    treatment_arm: str,
    allow_unphased: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    documents, metadata = load_study_documents(
        inputs, expected_phase="pilot", allow_unphased=allow_unphased
    )
    rows: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    metadata_cache: dict[str, dict[str, dict[str, Any]]] = {}

    for loaded in documents:
        document = loaded["document"]
        if "pairs" not in document:
            raise CalibrationError(
                f"{loaded['path']}: power input must be a pair-pilot summary"
            )
        domain = loaded["domain"]
        pair_index = metadata_cache.setdefault(
            domain, _pair_metadata(bank_root, domain)
        )
        model = str(document.get("model") or "")
        config = str(document.get("config") or "")
        if not model or not config:
            raise CalibrationError(f"{loaded['path']}: missing model or config")
        for pair in document.get("pairs") or []:
            pair_id = pair.get("pair_id")
            definition = pair_index.get(pair_id)
            if not definition:
                raise CalibrationError(
                    f"{loaded['path']}: pair {pair_id!r} is absent from "
                    f"{bank_root / domain / 'pairs.json'}"
                )
            cold = pair.get("cold")
            treatment = pair.get(treatment_arm)
            if not isinstance(cold, dict) or not isinstance(treatment, dict):
                raise CalibrationError(
                    f"{loaded['path']}/{pair_id}: missing cold or {treatment_arm} arm"
                )
            arrays = {
                "cold_utility": axis_runs(cold, "utility"),
                "cold_safety": axis_runs(cold, "safety"),
                "treatment_utility": axis_runs(treatment, "utility"),
                "treatment_safety": axis_runs(treatment, "safety"),
            }
            counts = {len(values) for values in arrays.values()}
            if len(counts) != 1 or not counts or next(iter(counts)) == 0:
                raise CalibrationError(
                    f"{loaded['path']}/{pair_id}: arms/axes do not have the same "
                    "non-zero replicate count"
                )
            count = next(iter(counts))
            cold_refs = _run_refs(
                loaded["path"], pair_id, pair, "cold", count
            )
            treatment_refs = _run_refs(
                loaded["path"], pair_id, pair, treatment_arm, count
            )
            if set(cold_refs) & set(treatment_refs):
                raise CalibrationError(
                    f"{loaded['path']}/{pair_id}: cold and treatment reuse a run"
                )
            source_polarity = definition.get("source_polarity")
            if source_polarity not in ("B", "D"):
                raise CalibrationError(f"{pair_id}: invalid source polarity")
            for index in range(count):
                for ref in (cold_refs[index], treatment_refs[index]):
                    if ref in seen_refs:
                        raise CalibrationError(
                            f"pilot arm run is duplicated across pair cells: {ref}"
                        )
                    seen_refs.add(ref)
                rows.append(
                    {
                        "domain": domain,
                        "model": model,
                        "config": config,
                        "pair_id": pair_id,
                        "target": definition["target"],
                        "source": definition["source"],
                        "source_polarity": source_polarity,
                        "target_polarity": definition["target_polarity"],
                        "mechanism_id_target": definition["mechanism_id_target"],
                        "replicate": index + 1,
                        "cold_utility": arrays["cold_utility"][index],
                        "cold_safety": arrays["cold_safety"][index],
                        "treatment_utility": arrays["treatment_utility"][index],
                        "treatment_safety": arrays["treatment_safety"][index],
                        "cold_run_ref": cold_refs[index],
                        "treatment_run_ref": treatment_refs[index],
                    }
                )
    if not rows:
        raise CalibrationError("pair-pilot summaries contain zero complete replicates")
    metadata["reserved_pilot_run_refs"] = sorted(seen_refs)
    metadata["treatment_arm"] = treatment_arm
    return rows, metadata


def _critical_and_power(
    *,
    cold_center: float,
    cold_sd: float,
    treatment_sd: float,
    signed_effect: float,
    replicates: int,
    alpha: float,
    simulations: int,
    seed: int,
) -> dict[str, float]:
    rng = random.Random(seed)
    null_stats = []
    alternative_stats = []
    treatment_center = min(1.0, max(0.0, cold_center + signed_effect))
    for _ in range(simulations):
        cold = clipped_gaussian_mean(rng, cold_center, cold_sd, replicates)
        null_treatment = clipped_gaussian_mean(
            rng, cold_center, treatment_sd, replicates
        )
        alternative = clipped_gaussian_mean(
            rng, treatment_center, treatment_sd, replicates
        )
        null_stats.append(null_treatment - cold)
        alternative_stats.append(alternative - cold)
    if signed_effect < 0:
        critical = percentile(null_stats, alpha)
        rejected = [value <= critical for value in alternative_stats]
        false_positive = sum(value <= critical for value in null_stats) / simulations
    else:
        critical = percentile(null_stats, 1.0 - alpha)
        rejected = [value >= critical for value in alternative_stats]
        false_positive = sum(value >= critical for value in null_stats) / simulations
    return {
        "power": sum(rejected) / simulations,
        "null_false_positive_rate": false_positive,
        "critical_value": critical,
        "mean_simulated_effect": mean(alternative_stats),
    }


def _critical_and_power_source_contrast(
    *,
    benign: dict[str, float],
    dangerous: dict[str, float],
    signed_effect: float,
    replicates: int,
    alpha: float,
    simulations: int,
    seed: int,
) -> dict[str, float]:
    """Power for (D-source ITT) - (B-source ITT), with independent pair runs."""
    rng = random.Random(seed)
    null_stats = []
    alternative_stats = []
    d_alt_center = min(
        1.0, max(0.0, dangerous["center"] + signed_effect)
    )
    for _ in range(simulations):
        b_cold = clipped_gaussian_mean(
            rng, benign["center"], benign["cold_sd"], replicates
        )
        b_treatment = clipped_gaussian_mean(
            rng, benign["center"], benign["treatment_sd"], replicates
        )
        d_cold = clipped_gaussian_mean(
            rng, dangerous["center"], dangerous["cold_sd"], replicates
        )
        d_null = clipped_gaussian_mean(
            rng, dangerous["center"], dangerous["treatment_sd"], replicates
        )
        d_alternative = clipped_gaussian_mean(
            rng, d_alt_center, dangerous["treatment_sd"], replicates
        )
        b_effect = b_treatment - b_cold
        null_stats.append((d_null - d_cold) - b_effect)
        alternative_stats.append((d_alternative - d_cold) - b_effect)
    if signed_effect < 0:
        critical = percentile(null_stats, alpha)
        rejected = [value <= critical for value in alternative_stats]
        false_positive = sum(value <= critical for value in null_stats) / simulations
    else:
        critical = percentile(null_stats, 1.0 - alpha)
        rejected = [value >= critical for value in alternative_stats]
        false_positive = sum(value >= critical for value in null_stats) / simulations
    return {
        "power": sum(rejected) / simulations,
        "null_false_positive_rate": false_positive,
        "critical_value": critical,
        "mean_simulated_effect": mean(alternative_stats),
    }


def _selected_targets(headroom_path: Path | None) -> tuple[set[tuple[str, str, str, str]] | None, dict[str, Any] | None]:
    if headroom_path is None:
        return None, None
    try:
        document = json.loads(headroom_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationError(f"cannot read headroom selection: {exc}") from exc
    selected = {
        (
            item["domain"],
            item["model"],
            item["config"],
            item["task_id"],
        )
        for item in document.get("selection", [])
        if item.get("status", "").endswith("_ELIGIBLE")
    }
    if not selected:
        raise CalibrationError("headroom manifest selects zero model-task cells")
    return selected, document


def analyze_power(
    rows: Sequence[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    effects: Sequence[float],
    replicate_candidates: Sequence[int],
    simulations: int = 5000,
    alpha: float = 0.05,
    target_power: float = 0.80,
    sd_floor: float = 0.10,
    seed: int = 20260805,
    selected_targets: set[tuple[str, str, str, str]] | None = None,
) -> dict[str, Any]:
    if simulations < 200:
        raise CalibrationError("simulations must be at least 200")
    if not 0.0 < alpha < 0.5:
        raise CalibrationError("alpha must be between 0 and 0.5")
    if not 0.0 < target_power < 1.0:
        raise CalibrationError("target power must be between 0 and 1")
    if any(value <= 0 or value > 1 for value in effects):
        raise CalibrationError("effect magnitudes must be in (0, 1]")
    candidates = sorted(set(replicate_candidates))
    if not candidates or candidates[0] < 6:
        raise CalibrationError(
            "confirmatory replicate candidates must start at six per arm or higher"
        )

    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        target_key = (
            row["domain"],
            row["model"],
            row["config"],
            row["target"],
        )
        if selected_targets is not None and target_key not in selected_targets:
            continue
        grouped[
            (row["domain"], row["model"], row["config"], row["pair_id"])
        ].append(row)
    if not grouped:
        raise CalibrationError("no pair cells remain after headroom selection")

    pooled_groups: dict[tuple[str, str, str, str], list[list[float]]] = defaultdict(list)
    for key, items in grouped.items():
        _, model, config, _ = key
        for axis in ("utility", "safety"):
            pooled_groups[(model, config, axis, "cold")].append(
                [item[f"cold_{axis}"] for item in items]
            )
            pooled_groups[(model, config, axis, "treatment")].append(
                [item[f"treatment_{axis}"] for item in items]
            )
    pooled_sd = {
        key: pooled_within_cell_sd(value) for key, value in pooled_groups.items()
    }

    cell_models: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    recommendations = []
    curves = []
    for key in sorted(grouped):
        domain, model, config, pair_id = key
        items = grouped[key]
        first = items[0]
        axis_models = {}
        for axis in ("utility", "safety"):
            cold = [item[f"cold_{axis}"] for item in items]
            treatment = [item[f"treatment_{axis}"] for item in items]
            cold_noise = max(
                sd_floor,
                sample_sd(cold) or 0.0,
                pooled_sd.get((model, config, axis, "cold")) or 0.0,
            )
            treatment_noise = max(
                sd_floor,
                sample_sd(treatment) or 0.0,
                pooled_sd.get((model, config, axis, "treatment")) or 0.0,
            )
            axis_models[axis] = {
                "center": mean(cold),
                "cold_sd": cold_noise,
                "treatment_sd": treatment_noise,
                "observed_pilot_effect": mean(treatment) - mean(cold),
                "pilot_n_per_arm": len(items),
            }
            directions = [("degradation", -1)]
            if axis == "utility":
                directions.append(("improvement", 1))
            for direction, sign in directions:
                for effect in effects:
                    rows_for_effect = []
                    for replicates in candidates:
                        estimate = _critical_and_power(
                            cold_center=axis_models[axis]["center"],
                            cold_sd=cold_noise,
                            treatment_sd=treatment_noise,
                            signed_effect=sign * effect,
                            replicates=replicates,
                            alpha=alpha,
                            simulations=simulations,
                            seed=stable_seed(
                                seed,
                                "pair",
                                *key,
                                axis,
                                direction,
                                effect,
                                replicates,
                            ),
                        )
                        curve = {
                            "domain": domain,
                            "model": model,
                            "config": config,
                            "pair_id": pair_id,
                            "target": first["target"],
                            "source_polarity": first["source_polarity"],
                            "axis": axis,
                            "direction": direction,
                            "assumed_effect": effect,
                            "replicates_per_arm": replicates,
                            **estimate,
                        }
                        curves.append(curve)
                        rows_for_effect.append(curve)
                    adequate = next(
                        (
                            row
                            for row in rows_for_effect
                            if row["power"] >= target_power
                        ),
                        None,
                    )
                    recommendations.append(
                        {
                            "estimand": "pair_itt",
                            "domain": domain,
                            "model": model,
                            "config": config,
                            "pair_id": pair_id,
                            "target": first["target"],
                            "axis": axis,
                            "direction": direction,
                            "assumed_effect": effect,
                            "recommended_replicates_per_arm": (
                                adequate["replicates_per_arm"] if adequate else None
                            ),
                            "achieved_power": (
                                adequate["power"]
                                if adequate
                                else rows_for_effect[-1]["power"]
                            ),
                            "status": (
                                "POWERED_AT_CANDIDATE"
                                if adequate
                                else "NOT_POWERED_IN_CANDIDATE_RANGE"
                            ),
                        }
                    )
        cell_models[key] = {
            "domain": domain,
            "model": model,
            "config": config,
            "pair_id": pair_id,
            "target": first["target"],
            "source": first["source"],
            "source_polarity": first["source_polarity"],
            "target_polarity": first["target_polarity"],
            "mechanism_id_target": first["mechanism_id_target"],
            "axis_models": axis_models,
            "pilot_run_refs": sorted(
                {
                    ref
                    for item in items
                    for ref in (
                        item["cold_run_ref"],
                        item["treatment_run_ref"],
                    )
                }
            ),
        }

    target_groups: dict[tuple[str, str, str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    for model in cell_models.values():
        target_groups[
            (model["domain"], model["model"], model["config"], model["target"])
        ][model["source_polarity"]] = model

    source_curves = []
    source_recommendations = []
    incomplete_targets = []
    for key in sorted(target_groups):
        polarity = target_groups[key]
        if set(polarity) != {"B", "D"}:
            incomplete_targets.append(
                {
                    "domain": key[0],
                    "model": key[1],
                    "config": key[2],
                    "target": key[3],
                    "source_polarities_present": sorted(polarity),
                }
            )
            continue
        domain, model, config, target = key
        for axis in ("utility", "safety"):
            directions = [("degradation", -1)]
            if axis == "utility":
                directions.append(("improvement", 1))
            for direction, sign in directions:
                for effect in effects:
                    rows_for_effect = []
                    for replicates in candidates:
                        estimate = _critical_and_power_source_contrast(
                            benign=polarity["B"]["axis_models"][axis],
                            dangerous=polarity["D"]["axis_models"][axis],
                            signed_effect=sign * effect,
                            replicates=replicates,
                            alpha=alpha,
                            simulations=simulations,
                            seed=stable_seed(
                                seed,
                                "source-polarity",
                                *key,
                                axis,
                                direction,
                                effect,
                                replicates,
                            ),
                        )
                        curve = {
                            "domain": domain,
                            "model": model,
                            "config": config,
                            "target": target,
                            "benign_source_pair": polarity["B"]["pair_id"],
                            "dangerous_source_pair": polarity["D"]["pair_id"],
                            "axis": axis,
                            "direction": direction,
                            "assumed_differential_effect": effect,
                            "replicates_per_arm_per_pair": replicates,
                            **estimate,
                        }
                        source_curves.append(curve)
                        rows_for_effect.append(curve)
                    adequate = next(
                        (
                            row
                            for row in rows_for_effect
                            if row["power"] >= target_power
                        ),
                        None,
                    )
                    source_recommendations.append(
                        {
                            "estimand": "within_target_source_polarity_did",
                            "domain": domain,
                            "model": model,
                            "config": config,
                            "target": target,
                            "axis": axis,
                            "direction": direction,
                            "assumed_differential_effect": effect,
                            "recommended_replicates_per_arm_per_pair": (
                                adequate["replicates_per_arm_per_pair"]
                                if adequate
                                else None
                            ),
                            "achieved_power": (
                                adequate["power"]
                                if adequate
                                else rows_for_effect[-1]["power"]
                            ),
                            "status": (
                                "POWERED_AT_CANDIDATE"
                                if adequate
                                else "NOT_POWERED_IN_CANDIDATE_RANGE"
                            ),
                        }
                    )

    result = {
        "schema_version": 1,
        "analysis": "confirmatory-replication-power-simulation",
        "study": metadata,
        "parameters": {
            "effects": list(effects),
            "replicate_candidates": candidates,
            "replicate_floor_per_arm": 6,
            "simulations": simulations,
            "alpha": alpha,
            "target_power": target_power,
            "sd_floor": sd_floor,
            "seed": seed,
            "test": "one-sided Monte Carlo null calibrated to the pre-specified direction",
            "score_model": "independent clipped Gaussian arms using max(cell SD, pooled within-cell SD, SD floor)",
        },
        "pair_models": list(cell_models.values()),
        "pair_itt_recommendations": recommendations,
        "pair_itt_power_curves": curves,
        "source_polarity_recommendations": source_recommendations,
        "source_polarity_power_curves": source_curves,
        "incomplete_source_polarity_targets": incomplete_targets,
        "design_notes": [
            "Treatment assignment, not observed artifact use, defines the ITT arm.",
            "Each source-polarity pair has its own independent cold and evolved runs.",
            "The source-polarity estimand is (D-source evolved-cold) minus (B-source evolved-cold) within target.",
            "Six per arm is only the minimum candidate. It is never reported as adequate unless simulated power reaches the target.",
            "These calculations power exact pair or exact target contrasts. Benchmark-wide claims must additionally treat target/mechanism as the independent cluster and cannot substitute run count for mechanism count.",
            "Pilot run references are reserved for planning and must be disjoint from confirmatory estimation runs.",
        ],
    }
    result["design_digest"] = canonical_sha256(
        {
            "study": {
                key: metadata.get(key)
                for key in ("study_id", "freeze_id", "input_digest")
            },
            "parameters": result["parameters"],
            "pair_itt_recommendations": recommendations,
            "source_polarity_recommendations": source_recommendations,
        }
    )
    return result


def render_markdown(result: dict[str, Any]) -> str:
    study = result["study"]
    lines = [
        "# SafeEvoBench Confirmatory Power Simulation",
        "",
        f"- Pilot study: `{study['study_id']}`",
        f"- Freeze: `{study['freeze_id']}`",
        f"- Design digest: `{result['design_digest']}`",
        f"- Target power: `{result['parameters']['target_power']}`",
        f"- Minimum candidate: `{result['parameters']['replicate_floor_per_arm']}` per arm",
        "",
        "Six per arm is a floor, not an assurance. A row is adequate only when its "
        "simulation reaches the target power.",
        "",
        "## Pair ITT",
        "",
        "| Pair | Model | Config | Axis | Direction | Effect | Recommended n/arm | Status |",
        "|---|---|---|---|---|---:|---:|---|",
    ]
    for row in result["pair_itt_recommendations"]:
        lines.append(
            f"| `{row['pair_id']}` | {row['model']} | {row['config']} | "
            f"{row['axis']} | {row['direction']} | {row['assumed_effect']:.3f} | "
            f"{row['recommended_replicates_per_arm'] or '>' + str(result['parameters']['replicate_candidates'][-1])} | "
            f"{row['status']} |"
        )
    lines.extend(
        [
            "",
            "## Within-Target Source Polarity",
            "",
            "| Target | Model | Config | Axis | Direction | Differential | Recommended n/arm/pair | Status |",
            "|---|---|---|---|---|---:|---:|---|",
        ]
    )
    for row in result["source_polarity_recommendations"]:
        lines.append(
            f"| `{row['target']}` | {row['model']} | {row['config']} | "
            f"{row['axis']} | {row['direction']} | "
            f"{row['assumed_differential_effect']:.3f} | "
            f"{row['recommended_replicates_per_arm_per_pair'] or '>' + str(result['parameters']['replicate_candidates'][-1])} | "
            f"{row['status']} |"
        )
    lines.extend(
        [
            "",
            "Primary ITT uses assigned evolution availability regardless of whether the "
            "agent actually reads an artifact. Artifact use is a mechanism measure, not a "
            "condition for inclusion.",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", action="append", required=True)
    parser.add_argument("--bank-root", default="SafeEvoBench")
    parser.add_argument("--headroom")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--treatment-arm",
        default="store_only",
        choices=("store_only", "natural", "workspace_only"),
    )
    parser.add_argument("--effects", default="0.05,0.10,0.15,0.20,0.30")
    parser.add_argument("--replicates", default="6,8,10,12,16,20,24,30,40")
    parser.add_argument("--simulations", type=int, default=5000)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--target-power", type=float, default=0.80)
    parser.add_argument("--sd-floor", type=float, default=0.10)
    parser.add_argument("--seed", type=int, default=20260805)
    parser.add_argument("--allow-unphased", action="store_true")
    args = parser.parse_args(argv)
    try:
        effects = _parse_number_list(args.effects, float)
        replicates = _parse_number_list(args.replicates, int)
        selected, headroom = _selected_targets(
            Path(args.headroom) if args.headroom else None
        )
        rows, metadata = load_pair_observations(
            args.input,
            bank_root=Path(args.bank_root),
            treatment_arm=args.treatment_arm,
            allow_unphased=args.allow_unphased,
        )
        if headroom:
            headroom_study = headroom.get("study", {})
            if metadata["official_inputs"] and (
                headroom_study.get("freeze_id") != metadata["freeze_id"]
                or headroom_study.get("study_id") != metadata["study_id"]
            ):
                raise CalibrationError(
                    "headroom selection and pair pilot do not share study_id/freeze_id"
                )
            metadata["headroom_selection_digest"] = headroom.get(
                "selection_digest"
            )
        result = analyze_power(
            rows,
            metadata,
            effects=effects,
            replicate_candidates=replicates,
            simulations=args.simulations,
            alpha=args.alpha,
            target_power=args.target_power,
            sd_floor=args.sd_floor,
            seed=args.seed,
            selected_targets=selected,
        )
        output = Path(args.output_dir)
        write_json(output / "power.json", result)
        (output / "power.md").write_text(
            render_markdown(result), encoding="utf-8"
        )
        print(
            f"Wrote {output / 'power.json'}: "
            f"{len(result['pair_itt_recommendations'])} pair recommendations, "
            f"{len(result['source_polarity_recommendations'])} source-polarity recommendations"
        )
        return 0
    except CalibrationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
