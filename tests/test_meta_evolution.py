import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from continual_harness import cache
from continual_harness.agent import ContinualAgent
from continual_harness.config import BenchmarkSpec, HarnessConfig
from continual_harness.evolver.meta_processor import MetaProcessor
from continual_harness.sandbox import MockSandbox
from continual_harness.stores import memory as memory_module
from continual_harness.stores import skills as skills_module
from continual_harness.stores.memory import Memory
from continual_harness.stores.skills import SkillStore

TASK_COMPLETE_TOOL = {
    "name": "task_complete",
    "description": "Finish the task.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {"reason": {"type_": "STRING"}},
        "required": ["reason"],
    },
}


@pytest.fixture(autouse=True)
def reset_process_state(monkeypatch):
    monkeypatch.setattr(memory_module, "_memory_store", None)
    monkeypatch.setattr(skills_module, "_skill_store", None)
    monkeypatch.delenv("MEMORY_MODE", raising=False)
    cache.set_run_id(None)
    yield
    cache.set_run_id(None)


def install_stores(monkeypatch, run_dir: Path):
    memory = Memory(str(run_dir))
    skills = SkillStore(str(run_dir))
    monkeypatch.setattr(memory_module, "_memory_store", memory)
    monkeypatch.setattr(skills_module, "_skill_store", skills)
    return memory, skills


def make_agent(tmp_path, monkeypatch, config, tasks=None, run_name="test-run"):
    tasks = tasks or [
        {
            "id": "task-a",
            "name": "Task A",
            "user_prompt": "Complete task A.",
            "safety_label": "benign",
            "max_steps": 1,
        }
    ]
    group_dir = tmp_path / "group"
    group_dir.mkdir()
    (group_dir / "tasks.json").write_text(
        json.dumps(
            {
                "group": "test",
                "domain": "Test operations",
                "system_prompt": "Work in the test workspace.",
                "tasks": tasks,
            }
        )
    )
    cache_base = tmp_path / "cache"
    monkeypatch.setenv("AGENT_CACHE_BASE", str(cache_base))
    spec = BenchmarkSpec(
        name="test",
        base_tools=[TASK_COMPLETE_TOOL],
        dataset_role="Work in the test workspace.",
        cache_base=str(cache_base),
        snapshot_paths=[],
        domain="Test operations",
    )
    return ContinualAgent(
        model_name="primary-model",
        sandbox=MockSandbox(),
        group_dir=str(group_dir),
        spec=spec,
        config=config,
        run_name=run_name,
    )


@pytest.mark.parametrize(
    ("regular", "meta"),
    [
        ("memory", "meta_memory"),
        ("skills", "meta_skills"),
        ("evolve", "meta_prompt"),
    ],
)
def test_regular_and_meta_counterparts_conflict(regular, meta):
    with pytest.raises(ValueError, match="mutually exclusive"):
        HarnessConfig(**{regular: True, meta: True})


def test_independent_flags_replace_aggregate_and_forced_flags():
    config = HarnessConfig.from_flags(
        enable_meta_memory=True,
        enable_meta_skills=True,
        enable_meta_prompt=True,
        enable_planning=False,
    )
    assert config.enabled_meta_features() == [
        "meta_memory",
        "meta_skills",
        "meta_prompt",
    ]
    assert config.any_evolution
    assert not hasattr(config, "enable_evolution")
    assert not hasattr(config, "forced_evolve")
    with pytest.raises(TypeError):
        HarnessConfig.from_flags(enable_evolution=True)
    with pytest.raises(TypeError):
        HarnessConfig.from_flags(enable_forced_evolve=True)


def test_planning_is_opt_in_by_default():
    assert HarnessConfig().planning is False
    assert HarnessConfig.from_flags().planning is False
    assert HarnessConfig.from_flags(enable_planning=True).planning is True


def test_meta_counterparts_expose_no_primary_agent_tools(tmp_path, monkeypatch):
    agent = make_agent(
        tmp_path,
        monkeypatch,
        HarnessConfig(
            meta_memory=True,
            meta_skills=True,
            meta_prompt=True,
            subagents=True,
            planning=False,
            meta_model="review-model",
        ),
    )
    tool_names = {tool["name"] for tool in agent.tools}
    assert not tool_names & {
        "save_memory",
        "read_memory",
        "list_memory",
        "save_skill",
        "get_skill",
        "list_skills",
        "evolve_harness",
    }
    assert "spawn_subagent" in tool_names
    assert agent.meta_processor.model_name == "review-model"


def test_meta_model_defaults_to_primary_model(tmp_path, monkeypatch):
    case_dir = tmp_path / "default-model"
    case_dir.mkdir()
    agent = make_agent(
        case_dir,
        monkeypatch,
        HarnessConfig(meta_memory=True, planning=False),
    )
    assert agent.meta_processor.model_name == "primary-model"


def test_meta_writers_create_exactly_one_artifact_from_complete_task_snapshot(
    tmp_path, monkeypatch
):
    cache_base = tmp_path / "cache"
    run_dir = cache_base / "writer-run"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_CACHE_BASE", str(cache_base))
    cache.set_run_id("writer-run")
    memory, skills = install_stores(monkeypatch, run_dir)
    memory.add(
        path="prior",
        title="Existing memory",
        content="MEMORY_FULL_SENTINEL",
        created_in_task="older-task",
    )
    skills.add(
        path="prior",
        name="existing_skill",
        summary="Existing summary",
        description="SKILL_FULL_SENTINEL",
        code="printf existing",
        created_in_task="older-task",
    )

    calls = []
    memory_attempts = 0

    def fake_completion(prompt, model, module_name):
        nonlocal memory_attempts
        calls.append((prompt, model, module_name))
        if module_name == "MetaProcessor_Memory":
            memory_attempts += 1
            if memory_attempts == 1:
                return "not valid json"
            return json.dumps(
                {
                    "title": "New memory title",
                    "content": "A durable fact from the completed task.",
                }
            )
        assert module_name == "MetaProcessor_Skills"
        return json.dumps(
            {
                "name": "verify_then_apply",
                "summary": "Verify state before applying a change.",
                "description": "Inspect, apply, and verify the resulting state.",
                "code": "printf '%s\\n' \"$1\"",
            }
        )

    monkeypatch.setattr(
        "continual_harness.evolver.meta_processor.text_completion",
        fake_completion,
    )
    processor = MetaProcessor(
        model_name="meta-model",
        task_domain="Test operations",
        enabled_features=("meta_memory", "meta_skills"),
    )
    trajectory = [
        {
            "step": 1,
            "assistant_text": "INITIAL_ATTEMPT_SENTINEL",
            "tool_calls": [
                {
                    "tool": "bash",
                    "args": {"command": "inspect"},
                    "result": "initial result",
                }
            ],
        },
        {
            "step": 1,
            "assistant_text": "RETRY_ATTEMPT_SENTINEL",
            "tool_calls": [
                {
                    "tool": "task_complete",
                    "args": {"reason": "fixed on retry"},
                    "result": "completed",
                }
            ],
        },
    ]

    outputs = processor.process_task(
        task_id="task-a",
        task_prompt="Do the work.",
        completion_reason="fixed on retry",
        trajectory=trajectory,
        current_step=7,
    )

    assert [(output["feature"], output["status"]) for output in outputs] == [
        ("meta_memory", "created"),
        ("meta_skills", "created"),
    ]
    assert len(memory.entries) == 2
    assert len(skills.entries) == 2
    new_memory = next(entry for entry in memory.entries.values() if entry.title == "New memory title")
    new_skill = next(entry for entry in skills.entries.values() if entry.name == "verify_then_apply")
    assert new_memory.created_in_task == "meta_memory@task-a"
    assert new_skill.created_in_task == "meta_skills@task-a"
    assert new_skill.code == "printf '%s\\n' \"$1\""
    assert memory_attempts == 2
    assert all(model == "meta-model" for _, model, _ in calls)
    assert all("MEMORY_FULL_SENTINEL" in prompt for prompt, _, _ in calls)
    assert all("SKILL_FULL_SENTINEL" in prompt for prompt, _, _ in calls)
    assert all("INITIAL_ATTEMPT_SENTINEL" in prompt for prompt, _, _ in calls)
    assert all("RETRY_ATTEMPT_SENTINEL" in prompt for prompt, _, _ in calls)
    skill_prompt = next(
        prompt for prompt, _, module in calls if module == "MetaProcessor_Skills"
    )
    assert "New memory title" not in skill_prompt
    events = [
        json.loads(line)
        for line in (run_dir / "meta_events.jsonl").read_text().splitlines()
    ]
    assert [event["feature"] for event in events] == ["meta_memory", "meta_skills"]


def test_meta_processing_runs_only_after_completed_task(tmp_path, monkeypatch):
    tasks = [
        {
            "id": "completed",
            "name": "Completed",
            "user_prompt": "Finish this.",
            "safety_label": "benign",
            "max_steps": 1,
        },
        {
            "id": "incomplete",
            "name": "Incomplete",
            "user_prompt": "Do not finish this.",
            "safety_label": "benign",
            "max_steps": 1,
        },
    ]
    agent = make_agent(
        tmp_path,
        monkeypatch,
        HarnessConfig(meta_memory=True, planning=False, max_steps=1),
        tasks=tasks,
    )
    install_stores(monkeypatch, agent.cache_dir)

    class RecordingProcessor:
        def __init__(self):
            self.calls = []

        def process_task(self, **kwargs):
            self.calls.append(kwargs)
            return [
                {
                    "feature": "meta_memory",
                    "status": "created",
                    "task_id": kwargs["task_id"],
                }
            ]

    processor = RecordingProcessor()
    agent.meta_processor = processor

    class FakeLLM:
        def __init__(self, task_id):
            self.task_id = task_id

        def chat(self, _messages):
            if self.task_id == "completed":
                return {
                    "text": "",
                    "tool_calls": [
                        {
                            "id": "complete-1",
                            "name": "task_complete",
                            "args": {"reason": "done"},
                        }
                    ],
                }
            return {"text": "Still working.", "tool_calls": []}

    monkeypatch.setattr(
        agent,
        "_create_llm",
        lambda _system_prompt: FakeLLM(agent._current_task_id),
    )
    results = agent.run_group(max_retries=0)

    assert [result["completed"] for result in results] == [True, False]
    assert [call["task_id"] for call in processor.calls] == ["completed"]
    assert len(processor.calls[0]["trajectory"]) == 1
    assert results[0]["meta_outputs"][0]["status"] == "created"
    assert results[1]["meta_outputs"] == []


def test_full_meta_artifacts_are_injected_into_primary_and_subagent_prompts(
    tmp_path, monkeypatch
):
    agent = make_agent(
        tmp_path,
        monkeypatch,
        HarnessConfig(
            meta_memory=True,
            meta_skills=True,
            subagents=True,
            planning=False,
        ),
    )
    memory, skills = install_stores(monkeypatch, agent.cache_dir)
    memory.add(
        title="Source memory",
        content="PRIMARY_AND_SUBAGENT_MEMORY_SENTINEL",
        created_in_task="meta_memory@source",
    )
    skills.add(
        name="source_skill",
        summary="Source skill summary",
        description="PRIMARY_AND_SUBAGENT_SKILL_SENTINEL",
        code="printf injected-code",
        created_in_task="meta_skills@source",
    )
    agent._current_task_id = "target"
    agent._capture_meta_artifacts()

    primary_prompt = agent._build_system_prompt()
    assert "PRIMARY_AND_SUBAGENT_MEMORY_SENTINEL" in primary_prompt
    assert "PRIMARY_AND_SUBAGENT_SKILL_SENTINEL" in primary_prompt
    assert "printf injected-code" in primary_prompt
    agent._log_meta_artifact_pushes("orchestrator")

    captured = {}

    class CapturingLLM:
        def __init__(self, model, system_prompt, tools, **_kwargs):
            captured["model"] = model
            captured["system_prompt"] = system_prompt
            captured["tools"] = tools

        def chat(self, _messages):
            return {
                "text": "",
                "tool_calls": [
                    {
                        "id": "sub-complete",
                        "name": "task_complete",
                        "args": {"reason": "subagent done"},
                    }
                ],
            }

    monkeypatch.setattr("continual_harness.agent.LLMClient", CapturingLLM)
    entry = SimpleNamespace(
        name="reviewer",
        system_instructions="Review the task.",
        max_turns=1,
    )
    assert agent._run_subagent(entry, "Review this.", max_steps=1) == "subagent done"
    assert "PRIMARY_AND_SUBAGENT_MEMORY_SENTINEL" in captured["system_prompt"]
    assert "PRIMARY_AND_SUBAGENT_SKILL_SENTINEL" in captured["system_prompt"]
    subagent_tool_names = {tool["name"] for tool in captured["tools"]}
    assert not subagent_tool_names & {
        "save_memory",
        "read_memory",
        "list_memory",
        "save_skill",
        "get_skill",
        "list_skills",
    }

    events = [
        json.loads(line)
        for line in (agent.cache_dir / "transfer_events.jsonl").read_text().splitlines()
    ]
    assert len(events) == 4
    assert {event["kind"] for event in events} == {"content_push"}
    assert {event["recipient"] for event in events} == {
        "orchestrator",
        "subagent:reviewer",
    }
    assert all(event["source_tasks"] == ["source"] for event in events)


def test_meta_prompt_rewrites_only_prompt_state(tmp_path, monkeypatch):
    cache_base = tmp_path / "cache"
    run_dir = cache_base / "prompt-run"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_CACHE_BASE", str(cache_base))
    cache.set_run_id("prompt-run")
    memory, skills = install_stores(monkeypatch, run_dir)
    memory.add(title="Keep memory", content="unchanged", created_in_task="old")
    skills.add(
        name="keep_skill",
        summary="unchanged",
        description="unchanged",
        created_in_task="old",
    )
    memory_before = (run_dir / "memory.json").read_bytes()
    skills_before = (run_dir / "skills.json").read_bytes()

    processor = MetaProcessor(
        model_name="meta-model",
        task_domain="Test operations",
        enabled_features=("meta_prompt",),
    )
    seen = {}

    def fake_optimize(**kwargs):
        seen.update(kwargs)
        updated = processor.prompt_optimizer.current_base_prompt + "\n\nNew guidance."
        processor.prompt_optimizer.current_base_prompt = updated
        return updated

    monkeypatch.setattr(processor.prompt_optimizer, "optimize_prompt", fake_optimize)
    outputs = processor.process_task(
        task_id="task-a",
        task_prompt="Do task A.",
        completion_reason="done",
        trajectory=[
            {"step": 1, "assistant_text": "first", "tool_calls": []},
            {"step": 1, "assistant_text": "retry", "tool_calls": []},
        ],
        current_step=2,
    )

    assert outputs[0]["status"] == "rewritten"
    assert len(seen["trajectories"]) == 2
    assert memory_before == (run_dir / "memory.json").read_bytes()
    assert skills_before == (run_dir / "skills.json").read_bytes()
    assert processor.get_current_prompt().endswith("New guidance.")


def test_meta_prompt_receives_complete_tool_details(tmp_path, monkeypatch):
    cache_base = tmp_path / "cache"
    run_dir = cache_base / "prompt-details"
    run_dir.mkdir(parents=True)
    monkeypatch.setenv("AGENT_CACHE_BASE", str(cache_base))
    cache.set_run_id("prompt-details")

    processor = MetaProcessor(
        model_name="meta-model",
        task_domain="Test operations",
        enabled_features=("meta_prompt",),
    )
    captured = {}

    def fake_completion(prompt, model, module_name):
        captured["prompt"] = prompt
        captured["model"] = model
        captured["module_name"] = module_name
        return processor.prompt_optimizer.current_base_prompt + "\n\nDetailed guidance."

    monkeypatch.setattr(
        "continual_harness.llm.text_completion",
        fake_completion,
    )
    long_result = "RESULT_START_" + ("x" * 1200) + "_RESULT_END"
    outputs = processor.process_task(
        task_id="task-a",
        task_prompt="Do task A.",
        completion_reason="done",
        trajectory=[
            {
                "step": 1,
                "assistant_text": "Inspect the complete result.",
                "tool_calls": [
                    {
                        "tool": "bash",
                        "args": {"command": "printf TOOL_ARGUMENT_SENTINEL"},
                        "result": long_result,
                    }
                ],
            }
        ],
        current_step=1,
    )

    assert outputs[0]["status"] == "rewritten"
    assert "TOOL_ARGUMENT_SENTINEL" in captured["prompt"]
    assert long_result in captured["prompt"]
    assert captured["model"] == "meta-model"
    assert captured["module_name"] == "PromptOptimizer"
