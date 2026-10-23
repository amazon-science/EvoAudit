from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks.safeevobench import run_pairs
from continual_harness.config import HarnessConfig
from continual_harness.evolver.harness_evolver import HarnessEvolver
from continual_harness.evolver.meta_processor import MetaProcessor
from continual_harness.evolver.prompt_optimizer import PromptOptimizer
from continual_harness.prompts.compiler import (
    build_system_prompt,
    load_base_policy,
    load_evolution_variant,
)


def test_base_policy_contains_no_evolution_mechanism_guidance():
    policy = load_base_policy().lower()
    for forbidden in (
        "persistent",
        "memory",
        "skill",
        "subagent",
        "helper agent",
        "capture anything reusable",
        "build on your own prior work",
    ):
        assert forbidden not in policy


@pytest.mark.parametrize(
    ("family", "sentinel"),
    (
        ("memory", "Weak memory:"),
        ("skills", "Weak skill:"),
        ("subagents", "Weak specialist:"),
        ("evolve", "Weak reason:"),
    ),
)
def test_generalize_examples_compile_only_for_enabled_family(family, sentinel):
    compiled = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=[family],
        evolution_prompt_variant="generalize",
    )
    assert sentinel in compiled

    without_family = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=[
            other
            for other in ("memory", "skills", "subagents", "evolve")
            if other != family
        ],
        evolution_prompt_variant="generalize",
    )
    assert sentinel not in without_family


def test_current_variant_preserves_family_fragments_without_supplements():
    historical = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=["memory", "skills", "subagents", "evolve"],
    )
    current = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=["memory", "skills", "subagents", "evolve"],
        evolution_prompt_variant="current",
    )
    assert current == historical
    for sentinel in (
        "Weak memory:",
        "Weak skill:",
        "Weak specialist:",
        "Weak reason:",
    ):
        assert sentinel not in current


def test_evolution_prompt_variant_validation():
    assert HarnessConfig(memory=True).evolution_prompt_variant == "current"
    assert (
        HarnessConfig(
            skills=True, evolution_prompt_variant="generalize"
        ).evolution_prompt_variant
        == "generalize"
    )
    assert (
        HarnessConfig(
            subagents=True, evolution_prompt_variant="operative"
        ).evolution_prompt_variant
        == "operative"
    )
    with pytest.raises(ValueError, match="Unknown evolution_prompt_variant"):
        HarnessConfig(memory=True, evolution_prompt_variant="invented")
    with pytest.raises(ValueError, match="requires at least one"):
        HarnessConfig(evolution_prompt_variant="generalize")


@pytest.mark.parametrize(
    ("family", "sentinel"),
    (
        ("memory", "Weak memory:"),
        ("skills", "Make prior workflows control execution"),
        ("subagents", "Reuse reasoning through specialist delegation"),
        ("evolve", "Install better defaults for future tasks"),
    ),
)
def test_operative_guidance_compiles_only_for_enabled_family(family, sentinel):
    compiled = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=[family],
        evolution_prompt_variant="operative",
    )
    assert sentinel in compiled

    without_family = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=[
            other
            for other in ("memory", "skills", "subagents", "evolve")
            if other != family
        ],
        evolution_prompt_variant="operative",
    )
    assert sentinel not in without_family


def test_operative_guidance_has_mechanism_specific_adoption_rules():
    skills = load_evolution_variant("skills", "operative")
    subagents = load_evolution_variant("subagents", "operative")
    evolve = load_evolution_variant("evolve", "operative")

    assert "adopt its workflow as the initial plan" in skills
    assert "delegate before performing that analysis yourself" in subagents
    assert "at or below the current prompt's length" in evolve
    assert "delegate before performing" not in skills
    assert "adopt its workflow" not in subagents


def test_pair_runner_forwards_generalize_variant(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(run_pairs.subprocess, "run", fake_run)
    args = SimpleNamespace(
        group="group",
        model="actor",
        meta_model=None,
        memory_prompt_variant="current",
        evolution_prompt_variant="generalize",
        sandbox_mode="mock",
        enable_planning=False,
        judge=None,
        arm_timeout=0,
    )
    run_pairs._run_arm(
        args, tmp_path, "pair/evolve", ["source", "target"], "skills", 5000
    )
    command = captured["command"]
    index = command.index("--evolution-prompt-variant")
    assert command[index + 1] == "generalize"


class _AddStore:
    def add(self, **_fields):
        return "artifact_1"


def test_meta_writers_receive_only_their_own_generalize_examples(monkeypatch):
    processor = MetaProcessor(
        model_name="test-model",
        task_domain="operations",
        enabled_features=(),
        evolution_prompt_variant="generalize",
    )
    prompts = []

    def structured_completion(*, prompt, module_name, required_fields):
        prompts.append((module_name, prompt, tuple(required_fields)))
        if module_name.endswith("Memory"):
            return {"title": "Reusable memory", "content": "Reusable content"}
        return {
            "name": "reusable_skill",
            "summary": "Reusable summary",
            "description": "Reusable workflow",
            "code": "",
        }

    monkeypatch.setattr(
        processor, "_structured_completion", structured_completion
    )
    monkeypatch.setattr(
        "continual_harness.stores.memory.get_memory_store", lambda: _AddStore()
    )
    monkeypatch.setattr(
        "continual_harness.stores.skills.get_skill_store", lambda: _AddStore()
    )

    processor._create_memory(
        task_id="source",
        task_context="task",
        artifact_context="artifacts",
    )
    processor._create_skill(
        task_id="source",
        task_context="task",
        artifact_context="artifacts",
    )

    memory_prompt = prompts[0][1]
    skill_prompt = prompts[1][1]
    assert "Weak memory:" in memory_prompt
    assert "Weak skill:" not in memory_prompt
    assert "Weak skill:" in skill_prompt
    assert "Weak memory:" not in skill_prompt


@pytest.mark.parametrize(
    ("pass_name", "sentinel", "tools"),
    (
        ("subagents", "Weak specialist:", frozenset({"spawn_subagent"})),
        ("skills", "Weak skill:", frozenset({"save_skill"})),
        ("memory", "Weak memory:", frozenset({"save_memory"})),
    ),
)
def test_harness_evolver_family_passes_receive_generalize_guidance(
    monkeypatch, pass_name, sentinel, tools
):
    captured = {}

    def completion(prompt, _model, module_name):
        captured[module_name] = prompt
        return (
            '{"analysis": "none", "create": [], "add": [], '
            '"update": [], "retire": []}'
        )

    monkeypatch.setattr(
        "continual_harness.evolver.harness_evolver.text_completion",
        completion,
    )
    evolver = HarnessEvolver(
        model_name="test-model",
        run_data_manager=None,
        task_domain="operations",
        available_tools=tools,
        evolution_prompt_variant="generalize",
    )

    store = type(
        "Store",
        (),
        {"get_tree_overview": lambda self: "(empty)"},
    )()
    singular = pass_name[:-1] if pass_name.endswith("s") else pass_name
    monkeypatch.setattr(
        evolver, f"_get_{singular}_store", lambda: store
    )

    getattr(evolver, f"_evolve_{pass_name}")([], 1)
    prompt = next(iter(captured.values()))
    assert sentinel in prompt


def test_meta_prompt_optimizer_receives_meta_specific_example(
    tmp_path, monkeypatch
):
    base = tmp_path / "base.md"
    base.write_text("# Base\nDo the task.", encoding="utf-8")
    captured = {}

    def completion(prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return "# Improved\nDo the task."

    monkeypatch.setattr("continual_harness.llm.text_completion", completion)
    optimizer = PromptOptimizer(
        model_name="test-model",
        run_data_manager=None,
        base_prompt_path=str(base),
        system_prompt_path=str(tmp_path / "missing.md"),
        active_families=set(),
        evolution_prompt_variant="generalize",
        variant_mechanism="meta_prompt",
    )
    monkeypatch.setattr(
        optimizer, "_save_optimized_prompt", lambda *_args: None
    )
    optimizer.optimize_prompt(
        current_step=1,
        trajectories=[
            {
                "step": 1,
                "reasoning": "Completed work.",
                "action": {"tool_calls": []},
            }
        ],
    )
    assert "Weak edit:" in captured["prompt"]
    assert (
        load_evolution_variant("evolve", "generalize")
        not in captured["prompt"]
    )


def test_operative_prompt_optimizer_requests_compact_unwrapped_prompt(
    tmp_path, monkeypatch
):
    base = tmp_path / "base.md"
    base.write_text("# Base\nDo the task.", encoding="utf-8")
    captured = {}

    def completion(prompt, *_args, **_kwargs):
        captured["prompt"] = prompt
        return "# Base\nUse the learned default."

    monkeypatch.setattr("continual_harness.llm.text_completion", completion)
    optimizer = PromptOptimizer(
        model_name="test-model",
        run_data_manager=None,
        base_prompt_path=str(base),
        system_prompt_path=str(tmp_path / "missing.md"),
        active_families=set(),
        evolution_prompt_variant="operative",
        variant_mechanism="meta_prompt",
    )
    monkeypatch.setattr(
        optimizer, "_save_optimized_prompt", lambda *_args: None
    )
    optimizer.optimize_prompt(
        current_step=1,
        trajectories=[
            {
                "step": 1,
                "reasoning": "Completed work.",
                "action": {"tool_calls": []},
            }
        ],
    )

    prompt = captured["prompt"]
    assert "Install one compact strategy change" in prompt
    assert "do not add an analysis, preface, wrapper label" in prompt
    assert not prompt.rstrip().endswith("IMPROVED BASE PROMPT:")
