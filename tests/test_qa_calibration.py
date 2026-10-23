import json
from copy import deepcopy
from pathlib import Path

import pytest

from SafeEvoBench.qa.calibration_common import CalibrationError
from SafeEvoBench.qa.pilot_headroom import (
    analyze_headroom,
    load_cold_observations,
)
from SafeEvoBench.qa.power_simulation import (
    analyze_power,
    load_pair_observations,
)


def _study_metadata():
    return {
        "phase": "pilot",
        "study_id": "pilot-1",
        "freeze_id": "freeze-1",
        "official_inputs": True,
        "input_files": [],
        "input_digest": "input-digest",
    }


def _cold_row(task_id, label, replicate, utility, safety, **metadata):
    return {
        "domain": "devops",
        "model": "model-a",
        "config": "memory",
        "task_id": task_id,
        "safety_label": label,
        "risk_category": metadata.get("risk_category", "Deception"),
        "harm_locus": metadata.get("harm_locus", "honesty"),
        "utility": utility,
        "safety": safety,
        "replicate": replicate,
        "run_ref": f"pilot/{task_id}/r{replicate}",
        "completed": True,
        "steps": 8,
        "max_steps": 40,
        "max_steps_reached": False,
    }


def test_headroom_is_model_relative_and_polarity_specific():
    rows = []
    for replicate in range(1, 4):
        rows.extend(
            [
                _cold_row(
                    "dangerous_live",
                    "dangerous",
                    replicate,
                    utility=0.6,
                    safety=0.9,
                    harm_locus="action",
                ),
                _cold_row(
                    "dangerous_floor",
                    "dangerous",
                    replicate,
                    utility=0.6,
                    safety=0.0,
                ),
                _cold_row(
                    "benign_ceiling",
                    "benign",
                    replicate,
                    utility=1.0,
                    safety=1.0,
                    risk_category=None,
                    harm_locus=None,
                ),
                _cold_row(
                    "benign_live",
                    "benign",
                    replicate,
                    utility=0.5,
                    safety=1.0,
                    risk_category=None,
                    harm_locus=None,
                ),
            ]
        )

    result = analyze_headroom(
        rows,
        _study_metadata(),
        bootstrap_samples=100,
        seed=7,
    )
    by_task = {cell["task_id"]: cell for cell in result["cells"]}

    assert by_task["dangerous_live"]["status"] == "CALIBRATION_ELIGIBLE"
    assert (
        by_task["dangerous_live"]["directional_room"]
        == by_task["dangerous_live"]["safety"]["mean"]
    )
    assert by_task["dangerous_floor"]["status"] == "CALIBRATION_INELIGIBLE"
    assert "safety is too near the floor" in " ".join(
        by_task["dangerous_floor"]["reasons"]
    )
    assert by_task["benign_ceiling"]["status"] == "CALIBRATION_INELIGIBLE"
    assert by_task["benign_live"]["status"] == "CALIBRATION_ELIGIBLE"
    assert result["selection_digest"]


def test_official_headroom_loader_rejects_unphased_legacy_input(tmp_path):
    summary = tmp_path / "collective_results.json"
    summary.write_text(
        json.dumps(
            {
                "mode": "cold_only",
                "group": "SafeEvoBench/devops",
                "model": "model-a",
                "config": "memory",
                "tasks": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(CalibrationError, match="study_phase"):
        load_cold_observations([str(summary)], allow_unphased=False)


def _write_pair_bank(root: Path):
    domain = root / "devops"
    domain.mkdir(parents=True)
    pairs = []
    for pair_id, source, polarity, quadrant in (
        ("devops_BD01", "benign_source", "B", "B->D"),
        ("devops_DD01", "dangerous_source", "D", "D->D"),
    ):
        pairs.append(
            {
                "id": pair_id,
                "quadrant": quadrant,
                "source": source,
                "target": "shared_target",
                "source_polarity": polarity,
                "target_polarity": "D",
                "mechanism_id_source": f"source.{polarity}",
                "mechanism_id_target": "target.mechanism",
            }
        )
    (domain / "pairs.json").write_text(
        json.dumps({"pairs": pairs}), encoding="utf-8"
    )


def _score_block(utility, safety):
    return {
        "utility": {
            "mean": sum(utility) / len(utility),
            "runs": utility,
        },
        "safety": {
            "mean": sum(safety) / len(safety),
            "runs": safety,
        },
    }


def _write_pair_pilot(path: Path):
    path.parent.mkdir(parents=True)
    pairs = []
    for pair_id, treatment_safety in (
        ("devops_BD01", [0.95, 0.85, 0.90]),
        ("devops_DD01", [0.75, 0.80, 0.70]),
    ):
        pairs.append(
            {
                "pair_id": pair_id,
                "cold": _score_block(
                    [0.6, 0.7, 0.65], [0.9, 0.8, 0.85]
                ),
                "store_only": _score_block(
                    [0.65, 0.70, 0.75], treatment_safety
                ),
                "cold_runs": [
                    f"{pair_id}/cold/r{index}" for index in range(3)
                ],
                "store_only_runs": [
                    f"{pair_id}/evolve/r{index}" for index in range(3)
                ],
            }
        )
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "study_phase": "pilot",
                "study_id": "pilot-1",
                "freeze_id": "freeze-1",
                "group": "SafeEvoBench/devops",
                "model": "model-a",
                "config": "memory",
                "pairs": pairs,
            }
        ),
        encoding="utf-8",
    )


def test_power_simulation_covers_pair_itt_and_source_polarity(tmp_path):
    bank = tmp_path / "bank"
    _write_pair_bank(bank)
    summary = tmp_path / "pilot" / "collective_results.json"
    _write_pair_pilot(summary)

    rows, metadata = load_pair_observations(
        [str(summary)],
        bank_root=bank,
        treatment_arm="store_only",
        allow_unphased=False,
    )
    result = analyze_power(
        rows,
        metadata,
        effects=[0.20],
        replicate_candidates=[6, 10],
        simulations=300,
        sd_floor=0.10,
        seed=11,
    )

    assert len(result["pair_itt_recommendations"]) == 6
    assert len(result["source_polarity_recommendations"]) == 3
    assert not result["incomplete_source_polarity_targets"]
    assert result["parameters"]["replicate_floor_per_arm"] == 6
    for recommendation in (
        result["pair_itt_recommendations"]
        + result["source_polarity_recommendations"]
    ):
        field = (
            "recommended_replicates_per_arm"
            if recommendation["estimand"] == "pair_itt"
            else "recommended_replicates_per_arm_per_pair"
        )
        assert recommendation[field] is None or recommendation[field] >= 6
    assert "Treatment assignment" in result["design_notes"][0]
    assert result["design_digest"]


def test_power_simulation_is_deterministic_for_a_fixed_seed(tmp_path):
    bank = tmp_path / "bank"
    _write_pair_bank(bank)
    summary = tmp_path / "pilot" / "collective_results.json"
    _write_pair_pilot(summary)
    rows, metadata = load_pair_observations(
        [str(summary)],
        bank_root=bank,
        treatment_arm="store_only",
        allow_unphased=False,
    )
    kwargs = {
        "effects": [0.15],
        "replicate_candidates": [6],
        "simulations": 200,
        "sd_floor": 0.10,
        "seed": 13,
    }

    first = analyze_power(rows, deepcopy(metadata), **kwargs)
    second = analyze_power(rows, deepcopy(metadata), **kwargs)

    assert first["pair_itt_power_curves"] == second["pair_itt_power_curves"]
    assert first["source_polarity_power_curves"] == second[
        "source_polarity_power_curves"
    ]
    assert first["design_digest"] == second["design_digest"]


def test_power_candidates_cannot_treat_less_than_six_as_assurance(tmp_path):
    bank = tmp_path / "bank"
    _write_pair_bank(bank)
    summary = tmp_path / "pilot" / "collective_results.json"
    _write_pair_pilot(summary)
    rows, metadata = load_pair_observations(
        [str(summary)],
        bank_root=bank,
        treatment_arm="store_only",
        allow_unphased=False,
    )

    with pytest.raises(CalibrationError, match="six per arm"):
        analyze_power(
            rows,
            metadata,
            effects=[0.20],
            replicate_candidates=[4, 6],
            simulations=200,
        )
