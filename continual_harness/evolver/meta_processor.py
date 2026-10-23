"""Harness-controlled post-task memory, skill, and prompt evolution."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from continual_harness.evolver.prompt_optimizer import PromptOptimizer
from continual_harness.llm import text_completion
from continual_harness.prompts.paths import (
    CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH,
    CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH,
)
from continual_harness.prompts.compiler import load_evolution_variant

logger = logging.getLogger(__name__)


class MetaProcessor:
    """Create harness-owned artifacts from one completed task at a time."""

    def __init__(
        self,
        *,
        model_name: str,
        task_domain: str,
        enabled_features: Iterable[str],
        active_families: Optional[set] = None,
        initial_prompt_override: Optional[str] = None,
        edit_history_n: int = 3,
        evolution_prompt_variant: str = "current",
    ):
        self.model_name = model_name
        self.task_domain = task_domain
        self.enabled_features = tuple(enabled_features)
        self.edit_history_n = max(0, int(edit_history_n))
        self.evolution_prompt_variant = evolution_prompt_variant
        self._prompt_history: List[Dict[str, Any]] = []
        self.prompt_optimizer: Optional[PromptOptimizer] = None

        if "meta_prompt" in self.enabled_features:
            self.prompt_optimizer = PromptOptimizer(
                model_name=model_name,
                run_data_manager=None,
                base_prompt_path=CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH,
                system_prompt_path=CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH,
                initial_prompt_override=initial_prompt_override,
                task_domain=task_domain,
                active_families=active_families or set(),
                evolution_prompt_variant=evolution_prompt_variant,
                variant_mechanism="meta_prompt",
            )

    @staticmethod
    def _memory_snapshot() -> List[Dict[str, Any]]:
        from continual_harness.stores.memory import get_memory_store

        entries = sorted(
            get_memory_store().entries.values(),
            key=lambda entry: (entry.created_at or "", entry.id),
        )
        return [
            {
                "id": entry.id,
                "path": entry.path,
                "title": entry.title,
                "content": entry.content,
                "source": entry.source,
                "created_in_task": entry.created_in_task,
            }
            for entry in entries
        ]

    @staticmethod
    def _skill_snapshot() -> List[Dict[str, Any]]:
        from continual_harness.stores.skills import get_skill_store

        entries = sorted(
            get_skill_store().entries.values(),
            key=lambda entry: (entry.created_at or "", entry.id),
        )
        return [
            {
                "id": entry.id,
                "path": entry.path,
                "name": entry.name,
                "summary": entry.summary,
                "description": entry.description,
                "code": entry.code,
                "source": entry.source,
                "created_in_task": entry.created_in_task,
            }
            for entry in entries
        ]

    @staticmethod
    def normalize_trajectory(
        task_id: str, task_domain: str, trajectory: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Convert every task-local step to the evolver's log schema without elision."""
        normalized: List[Dict[str, Any]] = []
        for sequence, step in enumerate(trajectory, 1):
            calls = []
            for call in step.get("tool_calls", []) or []:
                calls.append(
                    {
                        "name": call.get("tool") or call.get("name") or "unknown",
                        "args": call.get("args") or {},
                        "result": call.get("result"),
                    }
                )
            normalized.append(
                {
                    "step": sequence,
                    "task_step": step.get("step", sequence),
                    "reasoning": step.get("assistant_text") or "",
                    "action": {"tool_calls": calls},
                    "pre_state": {
                        "scenario": task_id,
                        "scenario_step": step.get("step", sequence),
                        "location": task_domain,
                    },
                }
            )
        return normalized

    @staticmethod
    def _parse_json_object(text: str) -> Optional[Dict[str, Any]]:
        candidate = (text or "").strip()
        if candidate.startswith("```"):
            candidate = re.sub(r"^```(?:json)?\s*", "", candidate)
            candidate = re.sub(r"\s*```$", "", candidate)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start < 0 or end <= start:
                return None
            try:
                parsed = json.loads(candidate[start : end + 1])
            except json.JSONDecodeError:
                return None
        return parsed if isinstance(parsed, dict) else None

    def _structured_completion(
        self,
        *,
        prompt: str,
        module_name: str,
        required_fields: Iterable[str],
    ) -> Dict[str, Any]:
        required = tuple(required_fields)
        last_error = "invalid response"
        request = prompt
        for attempt in range(2):
            response = text_completion(request, self.model_name, module_name)
            parsed = self._parse_json_object(response)
            missing = [
                field
                for field in required
                if not isinstance((parsed or {}).get(field), str)
                or not (parsed or {}).get(field, "").strip()
            ]
            if parsed is not None and not missing:
                return parsed
            last_error = (
                "response was not a JSON object"
                if parsed is None
                else f"missing non-empty string fields: {', '.join(missing)}"
            )
            if attempt == 0:
                request = (
                    prompt
                    + "\n\nYour previous response was invalid because "
                    + last_error
                    + ". Return exactly one valid JSON object and nothing else."
                )
        raise ValueError(last_error)

    @staticmethod
    def _artifact_context(
        memories: List[Dict[str, Any]], skills: List[Dict[str, Any]]
    ) -> str:
        return (
            "## Existing Memories\n"
            + json.dumps(memories, indent=2, ensure_ascii=True)
            + "\n\n## Existing Skills\n"
            + json.dumps(skills, indent=2, ensure_ascii=True)
        )

    @staticmethod
    def _task_context(
        *,
        task_id: str,
        task_prompt: str,
        completion_reason: str,
        trajectories: List[Dict[str, Any]],
    ) -> str:
        return f"""## Completed Task
Task ID: {task_id}
Task prompt:
{task_prompt}

Completion reason:
{completion_reason}

## Complete Task Trajectory
{json.dumps(trajectories, indent=2, ensure_ascii=True, default=str)}
"""

    def _create_memory(
        self,
        *,
        task_id: str,
        task_context: str,
        artifact_context: str,
    ) -> str:
        variant_guidance = load_evolution_variant(
            "meta_memory", self.evolution_prompt_variant
        )
        if variant_guidance:
            variant_guidance = "\n\n" + variant_guidance
        prompt = f"""You are the meta-memory writer for an AI agent working on {self.task_domain}.

After every completed task you MUST create exactly one memory that is possibly useful on a
future task. Select the highest-value factual observation, stable constraint, failure lesson,
or decision-relevant insight supported by the trajectory. Do not duplicate an existing
memory, invent facts, or write a reusable procedure that belongs in a skill.
{variant_guidance}

{artifact_context}

{task_context}

Return ONLY one JSON object:
{{"title": "short specific title", "content": "self-contained, portable decision-relevant lesson"}}
"""
        spec = self._structured_completion(
            prompt=prompt,
            module_name="MetaProcessor_Memory",
            required_fields=("title", "content"),
        )

        from continual_harness.stores.memory import get_memory_store

        return get_memory_store().add(
            path=f"meta/{task_id}",
            title=spec["title"].strip(),
            content=spec["content"].strip(),
            importance=3,
            source="meta",
            created_in_task=f"meta_memory@{task_id}",
        )

    def _create_skill(
        self,
        *,
        task_id: str,
        task_context: str,
        artifact_context: str,
    ) -> str:
        variant_guidance = load_evolution_variant(
            "meta_skills", self.evolution_prompt_variant
        )
        if variant_guidance:
            variant_guidance = "\n\n" + variant_guidance
        prompt = f"""You are the meta-skill writer for an AI agent working on {self.task_domain}.

After every completed task you MUST create exactly one skill that is possibly useful on a
future task. Select the most reusable procedure supported by the trajectory. The description
must explain when to use it, the ordered workflow, verification, and concrete pitfalls. Do
not duplicate an existing skill or store task-specific facts that belong in memory. Include
optional executable code only when a parameterized bash snippet genuinely helps.
{variant_guidance}

{artifact_context}

{task_context}

Return ONLY one JSON object:
{{
  "name": "short_snake_case_name",
  "summary": "one-line applicability summary",
  "description": "complete reusable workflow",
  "code": "optional bash snippet, or an empty string"
}}
"""
        spec = self._structured_completion(
            prompt=prompt,
            module_name="MetaProcessor_Skills",
            required_fields=("name", "summary", "description"),
        )

        from continual_harness.stores.skills import get_skill_store

        return get_skill_store().add(
            path=f"meta/{task_id}",
            name=spec["name"].strip(),
            summary=spec["summary"].strip(),
            description=spec["description"].strip(),
            code=str(spec.get("code") or "").strip(),
            effectiveness="medium",
            importance=3,
            source="meta",
            created_in_task=f"meta_skills@{task_id}",
        )

    def _recent_prompt_edits(self) -> str:
        if not self._prompt_history or self.edit_history_n <= 0:
            return ""
        recent = self._prompt_history[-self.edit_history_n :]
        lines = [
            f"- task {entry['task_id']} at step {entry['global_step']}: rewrote the base prompt"
            for entry in recent
        ]
        return (
            "## Recent meta-prompt edits\n"
            "These rewrites already happened; build on them instead of repeating them.\n"
            + "\n".join(lines)
            + "\n"
        )

    def _rewrite_prompt(
        self,
        *,
        task_id: str,
        current_step: int,
        trajectories: List[Dict[str, Any]],
    ) -> bool:
        if self.prompt_optimizer is None:
            return False
        previous = self.prompt_optimizer.get_current_prompt()
        updated = self.prompt_optimizer.optimize_prompt(
            current_step=current_step,
            num_trajectory_steps=len(trajectories),
            recent_edits=self._recent_prompt_edits(),
            trajectories=trajectories,
        )
        rewritten = bool(updated and updated.strip() and updated != previous)
        if rewritten:
            self._prompt_history.append(
                {
                    "task_id": task_id,
                    "global_step": current_step,
                    "timestamp": datetime.now().isoformat(),
                }
            )
        return rewritten

    def get_current_prompt(self) -> Optional[str]:
        if self.prompt_optimizer is None:
            return None
        return self.prompt_optimizer.get_current_prompt()

    @staticmethod
    def _write_event(event: Dict[str, Any]) -> None:
        try:
            from continual_harness.cache import get_cache_path

            with get_cache_path("meta_events.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=True) + "\n")
        except Exception as exc:
            logger.warning("Failed to persist meta event: %s", exc)

    def process_task(
        self,
        *,
        task_id: str,
        task_prompt: str,
        completion_reason: str,
        trajectory: List[Dict[str, Any]],
        current_step: int,
    ) -> List[Dict[str, Any]]:
        """Run enabled meta passes against one immutable completed-task snapshot."""
        normalized = self.normalize_trajectory(task_id, self.task_domain, trajectory)
        has_writer = bool(
            {"meta_memory", "meta_skills"} & set(self.enabled_features)
        )
        memories = self._memory_snapshot() if has_writer else []
        skills = self._skill_snapshot() if has_writer else []
        artifact_context = self._artifact_context(memories, skills)
        task_context = self._task_context(
            task_id=task_id,
            task_prompt=task_prompt,
            completion_reason=completion_reason,
            trajectories=normalized,
        )

        outputs: List[Dict[str, Any]] = []
        for feature in self.enabled_features:
            event: Dict[str, Any] = {
                "timestamp": datetime.now().isoformat(),
                "task_id": task_id,
                "global_step": current_step,
                "feature": feature,
                "model": self.model_name,
            }
            try:
                if feature == "meta_memory":
                    event["artifact_id"] = self._create_memory(
                        task_id=task_id,
                        task_context=task_context,
                        artifact_context=artifact_context,
                    )
                    event["status"] = "created"
                elif feature == "meta_skills":
                    event["artifact_id"] = self._create_skill(
                        task_id=task_id,
                        task_context=task_context,
                        artifact_context=artifact_context,
                    )
                    event["status"] = "created"
                elif feature == "meta_prompt":
                    event["status"] = (
                        "rewritten"
                        if self._rewrite_prompt(
                            task_id=task_id,
                            current_step=current_step,
                            trajectories=normalized,
                        )
                        else "unchanged"
                    )
                else:
                    event["status"] = "skipped"
                    event["error"] = f"unknown meta feature: {feature}"
            except Exception as exc:
                logger.error("Meta pass %s failed for task %s: %s", feature, task_id, exc)
                event["status"] = "error"
                event["error"] = str(exc)
            outputs.append(event)
            self._write_event(event)
        return outputs
