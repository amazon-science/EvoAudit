import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchmarks.safeevobench import run as run_module
from benchmarks.safeevobench import run_cold, run_factorial, run_pairs
from benchmarks.safeevobench.analysis_utils import _ArmScanner
from benchmarks.safeevobench.reuse_audit import (
    _pulled_source_artifact,
    _source_artifact_accesses,
)
from benchmarks.safeevobench.run import compute_meta_metrics, merge_meta_metrics


def test_primary_cli_has_no_framing_switch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        run_module.main()
    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--neutral-framing" not in help_text
    assert "--force-non-neutral" not in help_text


def test_primary_cli_documents_planning_as_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["run.py", "--help"])
    with pytest.raises(SystemExit) as exc_info:
        run_module.main()
    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    assert "--enable-planning" in help_text
    assert "off by default" in help_text
    assert "Pass --enable-planning to opt in" in help_text


def test_runner_presets_use_independent_flags_and_have_meta_variants():
    expected_all = {
        "--enable-memory",
        "--enable-skills",
        "--enable-subagents",
        "--enable-evolve",
    }
    for presets in (run_pairs._CONFIG_FLAGS, run_cold._CONFIG_FLAGS):
        flattened = {flag for flags in presets.values() for flag in flags}
        assert presets["all"] == [
            "--enable-memory",
            "--enable-skills",
            "--enable-subagents",
            "--enable-evolve",
        ]
        assert set(presets["all"]) == expected_all
        assert presets["meta_memory"] == ["--enable-meta-memory"]
        assert presets["meta_skills"] == ["--enable-meta-skills"]
        assert presets["meta_prompt"] == ["--enable-meta-prompt"]
        assert presets["meta_evolve"] == ["--enable-meta-prompt"]
        assert presets["no_planning"] == []
        assert set(presets["meta_all"]) == {
            "--enable-meta-memory",
            "--enable-meta-skills",
            "--enable-meta-prompt",
        }
        assert "--enable-evolution" not in flattened
        assert "--forced-evolve" not in flattened
        assert not any("forced" in name for name in presets)


def _completed_process():
    return SimpleNamespace(returncode=0, stdout="", stderr="")


def test_pair_runner_forwards_meta_model(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        run_pairs.subprocess,
        "run",
        lambda command, **_kwargs: captured.setdefault("command", command)
        and _completed_process(),
    )
    args = SimpleNamespace(
        group="group",
        model="primary",
        meta_model="reviewer",
        sandbox_mode="mock",
        enable_planning=False,
        judge=None,
        arm_timeout=0,
    )
    run_pairs._run_arm(
        args,
        tmp_path,
        "pair/evolve",
        ["source", "target"],
        "meta_memory",
        5000,
    )
    command = captured["command"]
    assert command[command.index("--meta-model") + 1] == "reviewer"
    assert "--enable-meta-memory" in command
    assert "--enable-evolution" not in command
    assert "--neutral-framing" not in command
    assert "--force-non-neutral" not in command


def test_cold_and_factorial_runners_forward_meta_model(monkeypatch, tmp_path):
    cold_command = {}
    monkeypatch.setattr(
        run_cold.subprocess,
        "run",
        lambda command, **_kwargs: cold_command.setdefault("value", command)
        and _completed_process(),
    )
    cold_args = SimpleNamespace(
        group="group",
        model="primary",
        meta_model="reviewer",
        sandbox_mode="mock",
        enable_planning=False,
        max_steps_per_task=0,
        judge="",
        arm_timeout=0,
        config="meta_skills",
    )
    run_cold._run_one(cold_args, tmp_path, "cold", "target", 5000)
    assert cold_command["value"][cold_command["value"].index("--meta-model") + 1] == "reviewer"
    assert "--enable-meta-skills" in cold_command["value"]
    assert "--neutral-framing" not in cold_command["value"]

    factorial_command = {}
    monkeypatch.setattr(
        run_factorial.subprocess,
        "run",
        lambda command, **_kwargs: factorial_command.setdefault("value", command)
        and _completed_process(),
    )
    factorial_args = SimpleNamespace(
        group="group",
        model="primary",
        meta_model="reviewer",
        sandbox_mode="mock",
        enable_planning=False,
        max_steps=None,
        judge=None,
        arm_timeout=0,
    )
    run_factorial._run_unit(
        factorial_args,
        tmp_path,
        "unit",
        ["target"],
        "meta_prompt",
        5001,
    )
    command = factorial_command["value"]
    assert command[command.index("--meta-model") + 1] == "reviewer"
    assert "--enable-meta-prompt" in command
    assert "--neutral-framing" not in command
    assert "--force-non-neutral" not in command


def test_factorial_runner_defaults_to_planning_off(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        run_factorial.subprocess,
        "run",
        lambda command, **_kwargs: captured.setdefault("command", command)
        and _completed_process(),
    )
    args = SimpleNamespace(
        group="group",
        model="primary",
        meta_model=None,
        sandbox_mode="mock",
        max_steps=None,
        judge=None,
        arm_timeout=0,
    )
    run_factorial._run_unit(
        args,
        tmp_path,
        "unit",
        ["target"],
        "base",
        5001,
    )
    command = captured["command"]
    assert "--no-enable-planning" in command
    assert "--enable-planning" not in command


def _write_transfer_events(run_dir: Path):
    events = [
        {
            "current_task": "target",
            "kind": "discovery",
            "tool": "list_memory",
            "source_tasks": ["source"],
            "artifacts": [{"origin_task": "source"}],
        },
        {
            "current_task": "target",
            "kind": "content_pull",
            "tool": "read_memory",
            "source_tasks": ["source"],
            "artifacts": [{"origin_task": "source"}],
        },
        {
            "current_task": "target",
            "kind": "content_push",
            "tool": "meta_memory_context",
            "source_tasks": ["source"],
            "artifacts": [
                {
                    "created_in_task": "meta_memory@source",
                    "origin_task": "source",
                }
            ],
        },
        {
            "current_task": "target",
            "kind": "content_push",
            "tool": "meta_memory_context",
            "source_tasks": ["unrelated"],
            "artifacts": [{"origin_task": "unrelated"}],
        },
    ]
    (run_dir / "transfer_events.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in events)
    )


def test_target_reuse_keeps_push_separate_from_pull_and_discovery(tmp_path):
    _write_transfer_events(tmp_path)
    assert run_pairs.target_reuse(tmp_path, ["source"], "target") == {
        "content_pull": 1,
        "content_push": 1,
        "discovery": 1,
        "prompt_pull": 0,
    }


def test_push_is_automatic_exposure_for_causal_and_reuse_audits(tmp_path):
    (tmp_path / "transfer_events.jsonl").write_text(
        json.dumps(
            {
                "current_task": "target",
                "kind": "content_push",
                "tool": "meta_skills_context",
                "source_tasks": ["source"],
                "artifacts": [{"created_in_task": "meta_skills@source"}],
            }
        )
        + "\n"
    )
    (tmp_path / "trajectory_history.jsonl").write_text(
        json.dumps(
            {
                "step": 1,
                "reasoning": "Act using the available context.",
                "action": {"tool_calls": []},
                "pre_state": {"scenario": "target"},
            }
        )
        + "\n"
    )
    assert _source_artifact_accesses(tmp_path, "target", {"source"}) == {"push"}
    assert _pulled_source_artifact(tmp_path, "target", {"source"})
    assert run_pairs.causal_evidence(tmp_path, ["source"], "target") == "used"


def test_analysis_scanner_does_not_classify_push_as_discovery(tmp_path):
    (tmp_path / "evaluation.json").write_text(
        json.dumps(
            {
                "tasks": {
                    "target": {
                        "utility": {"score": 1.0, "model": "judge"},
                        "harm": {"score": 0.0, "model": "judge"},
                    }
                },
                "evolution_metrics": {
                    "per_task": {
                        "source": {"steps": 1, "evolve_harness": 0},
                        "target": {"steps": 1, "completed": True},
                    }
                },
            }
        )
    )
    (tmp_path / "memory.json").write_text(
        json.dumps(
            {
                "entries": {
                    "m1": {"created_in_task": "meta_memory@source"}
                }
            }
        )
    )
    _write_transfer_events(tmp_path)

    detail = _ArmScanner().scan(tmp_path, "target", ["source"], natural=True)
    assert detail["pull_count"] == 1
    assert detail["push_count"] == 1
    assert detail["discovery_count"] == 1
    assert detail["pulled_source"]
    assert detail["pushed_source"]
    assert detail["source_exposed"]


def test_meta_output_counts_merge_into_evolution_metrics():
    results = [
        {
            "task_id": "a",
            "meta_outputs": [
                {"feature": "meta_memory", "status": "created"},
                {"feature": "meta_skills", "status": "created"},
                {"feature": "meta_prompt", "status": "rewritten"},
            ],
        },
        {
            "task_id": "b",
            "meta_outputs": [
                {"feature": "meta_prompt", "status": "unchanged"},
                {"feature": "meta_memory", "status": "error"},
            ],
        },
    ]
    meta = compute_meta_metrics(results)
    assert meta["aggregates"] == {
        "total_meta_memories_created": 1,
        "total_meta_skills_created": 1,
        "total_meta_prompt_rewrites": 1,
        "total_meta_prompt_unchanged": 1,
        "total_meta_errors": 1,
    }
    merged = merge_meta_metrics(
        {"per_task": {"a": {"steps": 3}}, "aggregates": {"total_evolve_calls": 0}},
        results,
    )
    assert merged["per_task"]["a"]["steps"] == 3
    assert merged["per_task"]["a"]["meta_prompt_rewritten"] == 1
    assert merged["aggregates"]["total_meta_errors"] == 1
