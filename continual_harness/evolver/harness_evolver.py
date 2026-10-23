#!/usr/bin/env python3
# Portions adapted from sethkarten/continual-harness (MIT License,
# Copyright (c) 2026 Seth Karten et al.), modified. See THIRD-PARTY-NOTICES.txt.
"""
HarnessEvolver — Full harness evolution for the ContinualHarness scaffold.

Subsumes PromptOptimizer and adds subagent, skill, and memory evolution.
Runs periodically (every N steps, after a minimum warmup) to analyze
recent trajectories and improve all harness components mid-episode.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from continual_harness.prompts.paths import (
    CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH,
    GAME_NAME,
    CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH,
    resolve_repo_path,
)
from continual_harness.evolver.prompt_optimizer import PromptOptimizer
from continual_harness.llm import text_completion
from continual_harness.prompts.compiler import (
    load_evolution_variant,
    load_memory_variant,
)
from continual_harness.tools import families as _families

logger = logging.getLogger(__name__)

# Evolution passes that touch a tool family: pass name -> family key in
# continual_harness.tools.families.FAMILIES. A pass runs only if the agent has
# at least one tool from that family. The prompt pass has no entry here — it is
# always run (the strategic prompt always exists).
_PASS_FAMILY = {
    "subagents": "subagents",
    "skills": "skills",
    "memory": "memory",
}

# Minimum steps before the first evolution fires.
MIN_WARMUP_STEPS = 25

# Evolution frequency adapts: frequent early (every 25 steps for first 200),
# then backs off (every 100 steps) once the harness stabilizes.
EARLY_PHASE_CUTOFF = 200
EARLY_FREQUENCY = 25
STABLE_FREQUENCY = 100

# Default tools (fallback when no available_tools is passed to HarnessEvolver)
_ALWAYS_AVAILABLE_TOOLS = frozenset({
    "bash",
    "task_complete",
    "save_memory",
    "read_memory",
    "save_skill",
    "get_skill",
    "spawn_subagent",
    "evolve_harness",
})


class HarnessEvolver:
    """Evolves all harness components: prompt, subagents, skills, memory."""

    def __init__(
        self,
        model_name: str,
        run_data_manager,
        base_prompt_path: str = CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH,
        system_prompt_path: str = CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH,
        initial_prompt_override: str | None = None,
        task_domain: str | None = None,
        available_tools: frozenset | None = None,
        edit_history_n: int = 3,
        evolution_prompt_variant: str = "current",
        memory_prompt_variant: str = "current",
    ):
        self.task_domain = task_domain or GAME_NAME
        self.available_tools = available_tools or _ALWAYS_AVAILABLE_TOOLS
        self.model_name = model_name
        # How many recent evolution generations of this agent's own edits to surface to
        # each pass (so it sees "what I already changed" and avoids re-proposing it).
        self.edit_history_n = max(0, int(edit_history_n))
        self.evolution_prompt_variant = evolution_prompt_variant
        self.memory_prompt_variant = memory_prompt_variant

        # Which evolution families this agent actually has (memory/skills/subagents).
        # Used to gate the corresponding evolution passes — the prompt pass always
        # runs. Tell the prompt optimizer too, so it only reasons about real tools.
        self.active_families = self._compute_active_families()

        self.prompt_optimizer = PromptOptimizer(
            model_name, run_data_manager, base_prompt_path, system_prompt_path,
            initial_prompt_override=initial_prompt_override,
            task_domain=self.task_domain,
            active_families=self.active_families,
            evolution_prompt_variant=evolution_prompt_variant,
            variant_mechanism="evolve",
        )
        self.run_manager = run_data_manager

        self.generation = 0
        self.evolution_log: List[Dict[str, Any]] = []

        logger.info(
            "HarnessEvolver initialized (warmup=%d steps, domain=%s, families=%s)",
            MIN_WARMUP_STEPS, self.task_domain, sorted(self.active_families),
        )

    def _compute_active_families(self) -> set:
        """Curation-target families (memory/skills/subagents) the agent has ≥1 tool for.

        Uses continual_harness.tools.families as the source of truth for which tool
        names belong to each family, so this stays in sync with the registry. Only
        the families that map to an evolution pass count — planning has no curation
        pass, and `evolve` is the trigger itself, not a thing evolve curates.
        """
        active = set()
        for fam_key in _PASS_FAMILY.values():  # {memory, skills, subagents}
            fam_tool_names = {t["name"] for t in _families.FAMILIES[fam_key].tools}
            if fam_tool_names & set(self.available_tools):
                active.add(fam_key)
        return active

    def _active_passes(self) -> list:
        """The evolution passes to run for this agent: prompt (always) + each
        family pass whose tools the agent actually has."""
        passes = ["prompt"]
        for pass_name, fam_key in _PASS_FAMILY.items():
            if fam_key in self.active_families:
                passes.append(pass_name)
        return passes

    # ------------------------------------------------------------------
    # Store accessors (lazy — imported only when evolution actually runs)
    # ------------------------------------------------------------------

    def _get_memory_store(self):
        from continual_harness.stores.memory import get_memory_store
        return get_memory_store()

    def _get_skill_store(self):
        from continual_harness.stores.skills import get_skill_store
        return get_skill_store()

    def _get_subagent_store(self):
        from continual_harness.stores.subagents import get_subagent_store
        return get_subagent_store()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_evolve(self, current_step: int, frequency: int) -> bool:
        """Return True if evolution should fire at this step.

        Uses adaptive frequency: evolve more often early (every 25 steps
        for the first 200 steps) to bootstrap the harness quickly, then
        back off to every 100 steps once capabilities stabilize.
        The caller's ``frequency`` arg is ignored in favor of the adaptive schedule.
        """
        if current_step < MIN_WARMUP_STEPS or current_step <= 0:
            return False
        effective_freq = EARLY_FREQUENCY if current_step <= EARLY_PHASE_CUTOFF else STABLE_FREQUENCY
        return current_step % effective_freq == 0

    def _evolved_provenance(self) -> str:
        """Provenance stamp for artifacts the evolver creates.

        Formatted as ``evolve@<task>`` so an evolver-created skill/memory/subagent
        is (a) attributable to the task during which evolution ran and (b)
        distinguishable from an artifact the agent saved directly. Falls back to a
        bare ``evolve`` marker when the evolving task is unknown.
        """
        task = getattr(self, "_evolving_task", "") or ""
        return f"evolve@{task}" if task else "evolve"

    def get_current_prompt(self) -> str:
        """Delegate to the inner PromptOptimizer."""
        return self.prompt_optimizer.get_current_prompt()

    def evolve(self, current_step: int, num_trajectory_steps: int = 50,
               current_task: str = "") -> Dict[str, Any]:
        """Run the applicable evolution passes and return a summary.

        The prompt pass always runs; the subagents/skills/memory passes run only
        when the agent actually has that tool family (see ``_active_passes``) — so
        evolution never curates components the agent can't use, and the prompt
        optimizer gets the agent's full attention. Each pass is independent — if
        one fails, the others still run and the evolution log is always saved.

        ``current_task`` is the task during which the agent invoked evolution; it
        is used to stamp provenance on any artifact the evolver creates (as
        ``evolve@<task>``) so evolver-created components are attributable in the
        transfer analysis and distinguishable from agent-saved ones.
        """
        # Provenance for artifacts this evolution run creates (read by the
        # _evolve_* passes at their store.add sites).
        self._evolving_task = current_task or ""
        logger.info(
            "=== HarnessEvolver generation %d at step %d (task=%s) ===",
            self.generation, current_step, current_task or "?",
        )

        trajectories = self.prompt_optimizer.get_recent_trajectories(num_trajectory_steps)
        if not trajectories:
            logger.warning("No trajectories — skipping evolution")
            return {"skipped": True, "reason": "no_trajectories"}

        active = set(self._active_passes())
        logger.info("Evolution passes for this config: %s", sorted(active))

        results: Dict[str, Any] = {}
        all_passes = [
            ("prompt", lambda: self._evolve_prompt(current_step, num_trajectory_steps)),
            ("subagents", lambda: self._evolve_subagents(trajectories, current_step)),
            ("skills", lambda: self._evolve_skills(trajectories, current_step)),
            ("memory", lambda: self._evolve_memory(trajectories, current_step)),
        ]
        for name, fn in all_passes:
            if name not in active:
                # Family not available to the agent — record why it didn't run so
                # the summary/log can distinguish "skipped" from "ran, no change".
                results[name] = {"skipped": f"no_{name}_tools"}
                continue
            try:
                results[name] = fn()
            except Exception as e:
                logger.error("Evolution pass '%s' failed: %s", name, e, exc_info=True)
                results[name] = {"error": str(e)}

        self.generation += 1
        self._save_evolution_log(current_step, results)
        return results

    # ------------------------------------------------------------------
    # Evolution passes
    # ------------------------------------------------------------------

    def _evolve_prompt(self, current_step: int, num_trajectory_steps: int) -> Dict[str, Any]:
        """Evolve the orchestrator base prompt via PromptOptimizer."""
        try:
            new_prompt = self.prompt_optimizer.optimize_prompt(
                current_step=current_step,
                num_trajectory_steps=num_trajectory_steps,
                recent_edits=self._recent_edits_digest("prompt"),
            )
            return {"rewritten": True, "length": len(new_prompt)}
        except Exception as e:
            logger.error("Prompt evolution failed: %s", e, exc_info=True)
            return {"rewritten": False, "error": str(e)}

    def _extract_tool_failures(self, trajectories: List[Dict[str, Any]]) -> str:
        """Extract tool failure patterns from trajectories for evolution analysis."""
        failures = []
        for traj in trajectories:
            action = traj.get("action", {})
            if not isinstance(action, dict):
                continue
            for tc in action.get("tool_calls", []):
                result = tc.get("result", "")
                result_str = str(result) if result else ""
                if not result_str:
                    continue
                # Check for failure indicators
                is_failure = False
                if isinstance(result, dict):
                    is_failure = result.get("success") is False or "error" in result
                elif '"success": false' in result_str.lower() or '"error"' in result_str.lower():
                    is_failure = True
                if is_failure:
                    failures.append({
                        "step": traj.get("step"),
                        "tool": tc.get("name"),
                        "args": str(tc.get("args", {}))[:200],
                        "error": result_str[:300],
                    })
        if not failures:
            return ""
        lines = ["## Tool Failures Detected"]
        for f in failures:
            lines.append(f"- Step {f['step']}: `{f['tool']}` args={f['args']} => {f['error']}")
        return "\n".join(lines)

    def _recent_edits_digest(self, family: str) -> str:
        """A compact record of THIS agent's own recent edits for one family, drawn from
        the last ``edit_history_n`` evolution generations. Lets a pass see 'what I already
        changed' so it stops re-proposing the same artifact and can build on prior edits.

        family: 'prompt' | 'subagents' | 'skills' | 'memory'.
        """
        if self.edit_history_n <= 0 or not self.evolution_log:
            return ""
        recent = self.evolution_log[-self.edit_history_n:]
        lines = []
        for e in recent:
            gen, step = e.get("generation", "?"), e.get("step", "?")
            if family == "prompt":
                if e.get("prompt_rewritten"):
                    lines.append(f"- gen {gen} (step {step}): rewrote the base prompt")
            else:
                created = e.get(f"{family}_created", []) or []
                updated = e.get(f"{family}_updated", []) or []
                retired = e.get(f"{family}_retired", []) or []
                parts = []
                if created:
                    parts.append(f"created {created}")
                if updated:
                    parts.append(f"updated {updated}")
                if retired:
                    parts.append(f"retired {retired}")
                if parts:
                    lines.append(f"- gen {gen} (step {step}): " + "; ".join(parts))
        if not lines:
            return ""
        header = (f"## Your recent {family} edits (last {len(recent)} generations)\n"
                  "You already made these changes — do NOT re-propose them; refine or build on them instead.\n")
        return header + "\n".join(lines) + "\n"

    def _evolve_subagents(
        self, trajectories: List[Dict[str, Any]], current_step: int
    ) -> Dict[str, Any]:
        """Analyze trajectories and create/update/retire subagents."""
        store = self._get_subagent_store()
        registry_overview = store.get_tree_overview()

        trajectory_summary = self.prompt_optimizer._format_trajectories_for_analysis(
            trajectories
        )
        tool_failures = self._extract_tool_failures(trajectories)
        recent_edits = self._recent_edits_digest("subagents")
        variant_guidance = load_evolution_variant(
            "subagents", self.evolution_prompt_variant
        )

        prompt = f"""You are a harness evolution system for an AI agent working on {self.task_domain}.
The agent learns entirely through task execution — no external references.

Your job: analyze recent trajectories and recommend changes to the agent's subagent library.

## How Subagents Work

Subagents are **typed specialists**. Each type has:
- A `name` (the type identifier, e.g., "csv_analyzer")
- A `description` (when to use this type)
- `system_instructions` (the system prompt defining the subagent's role and approach)
- `max_turns` (step budget per invocation)

The orchestrator spawns them with: `spawn_subagent(type="<name>", query="<specific task>")`
The query is passed as the user message. The subagent has access to bash, memory (read-only), and skills.

## Current Subagent Registry
{registry_overview}

{recent_edits}
## Recent Trajectories (last {len(trajectories)} steps)
{trajectory_summary}

{tool_failures}

{variant_guidance}

## Analysis Tasks

1. **Identify missing subagent types**: Look for repeated multi-step patterns the agent does manually that would benefit from a dedicated subagent type. Good candidates:
   - Recurring analysis patterns (e.g., "parse CSV and compute stats")
   - Service-specific checks the agent repeats across tasks
   - Investigation patterns that cross-reference multiple files

2. **Evaluate existing types**: Check if custom subagent types need their system_instructions refined (e.g., better output format, more specific guidance).

3. **Retire ineffective types**: If a type was used with consistently poor results, recommend removal.

## Output Format

Respond with ONLY a JSON object (no markdown fences):
{{
  "analysis": "Brief summary of what you observed",
  "create": [
    {{
      "name": "short_type_name",
      "description": "When to use this subagent type",
      "system_instructions": "Detailed system prompt: role, approach, output format, what to return via task_complete",
      "max_turns": 15
    }}
  ],
  "update": [
    {{
      "id": "sa_XXXX",
      "system_instructions": "improved system prompt",
      "description": "improved description",
      "max_turns": 20
    }}
  ],
  "retire": ["sa_XXXX"]
}}

Only include sections with actual recommendations. Empty arrays are fine.
Focus on reusable TYPES, not one-off tasks. A good type is one the agent will spawn many times with different queries.
"""

        try:
            response = text_completion(prompt, self.model_name, "HarnessEvolver_Subagents")
            recommendations = self._parse_json_response(response)
            if recommendations is None:
                return {"error": "failed_to_parse_response"}

            result = {"created": [], "updated": [], "retired": [], "analysis": recommendations.get("analysis", "")}

            # Create new subagent types
            for spec in recommendations.get("create", []):
                try:
                    entry_id = store.add(
                        path=f"evolved/{spec.get('name', 'unnamed').lower().replace(' ', '_')}",
                        name=spec.get("name", "Unnamed"),
                        description=spec.get("description", ""),
                        handler_type="looping",
                        max_turns=min(spec.get("max_turns", 15), 50),
                        system_instructions=spec.get("system_instructions", "")[:12000],
                        importance=3,
                        source="evolved",
                        created_in_task=self._evolved_provenance(),
                    )
                    result["created"].append(entry_id)
                    logger.info("Created evolved subagent type: %s (%s)", entry_id, spec.get("name"))
                except Exception as e:
                    logger.error("Failed to create subagent type %s: %s", spec.get("name"), e)

            # Update existing subagents
            for upd in recommendations.get("update", []):
                sid = upd.get("id")
                if not sid:
                    continue
                try:
                    fields = {k: v for k, v in upd.items() if k != "id" and v}
                    if fields:
                        store.update(sid, **fields)
                        result["updated"].append(sid)
                        logger.info("Updated evolved subagent: %s", sid)
                except Exception as e:
                    logger.error("Failed to update subagent %s: %s", sid, e)

            # Retire subagents
            for sid in recommendations.get("retire", []):
                try:
                    store.remove(sid)
                    result["retired"].append(sid)
                    logger.info("Retired evolved subagent: %s", sid)
                except Exception as e:
                    logger.error("Failed to retire subagent %s: %s", sid, e)

            return result

        except Exception as e:
            logger.error("Subagent evolution failed: %s", e, exc_info=True)
            return {"error": str(e)}

    def _evolve_skills(
        self, trajectories: List[Dict[str, Any]], current_step: int
    ) -> Dict[str, Any]:
        """Extract successful patterns as skills and update effectiveness."""
        store = self._get_skill_store()
        skill_overview = store.get_tree_overview()

        trajectory_summary = self.prompt_optimizer._format_trajectories_for_analysis(
            trajectories
        )
        tool_failures = self._extract_tool_failures(trajectories)
        recent_edits = self._recent_edits_digest("skills")
        variant_guidance = load_evolution_variant(
            "skills", self.evolution_prompt_variant
        )

        # Detect antipattern: lots of raw bash work but no skill capture/reuse — the
        # agent is re-deriving procedures instead of saving/retrieving them as skills.
        def _count(*names):
            target = set(names)
            return sum(
                1 for t in trajectories
                for tc in (t.get("action", {}).get("tool_calls", []) if isinstance(t.get("action", {}), dict) else [])
                if tc.get("name") in target
            )
        bash_count = _count("bash")
        # get_skill is current; run_skill is the legacy name — both count as reuse.
        skill_reuse_count = _count("get_skill", "run_skill")
        save_skill_count = _count("save_skill")
        antipattern_warning = ""
        if bash_count >= 8 and skill_reuse_count == 0 and save_skill_count == 0:
            antipattern_warning = f"""
## ANTIPATTERN DETECTED
The agent ran bash {bash_count} times but never saved a skill (save_skill) or retrieved one (get_skill) in the last {len(trajectories)} steps. If any of that work is a procedure it will face again, capture it as a skill: put the workflow steps in the description and, where the steps are a clean command sequence, include parameterized code. Recommend concrete skills below so the agent can get_skill it next time instead of re-deriving it.
"""

        prompt = f"""You are a harness evolution system analyzing an AI agent's recent task execution in {self.task_domain}.

Your job: identify reusable behavioral patterns (skills) from successful actions and evaluate existing skills.

## Current Skill Library
{skill_overview}

{recent_edits}
## Recent Trajectories (last {len(trajectories)} steps)
{trajectory_summary}

{tool_failures}
{antipattern_warning}
{variant_guidance}

## Optional Skill Code

The agent retrieves a skill, reads its workflow, and runs any attached code
itself with bash. Include code only when a clean command sequence is genuinely
reusable. Write a self-contained, parameterized bash snippet using positional
arguments such as `$1` and `$2`; otherwise leave `code` empty.

## Analysis Tasks

1. **Identify underperforming skills from reasoning traces**: Review the agent's reasoning to find skills that failed, errored, or produced undesirable outcomes. If the agent complained about a skill or abandoned it, recommend a clearer replacement workflow and replace its code when needed.

2. **Fix broken skills**: If a saved command sequence failed, replace it with a working parameterized bash snippet or remove the code and preserve the useful workflow.

3. **Record new skills**: Look for useful action and decision sequences. Include `code` only for repeatable command sequences. Make the workflow portable across related tasks in the domain.

4. **Update effectiveness ratings** based on trajectory outcomes.

## Output Format

Respond with ONLY a JSON object (no markdown fences):
{{
  "analysis": "Brief summary",
  "add": [
    {{
      "name": "string",
      "path": "category/subcategory",
      "summary": "One-line applicability summary",
      "description": "Complete reusable workflow",
      "code": "optional parameterized bash snippet",
      "effectiveness": "low|medium|high",
      "importance": 3
    }}
  ],
  "update": [
    {{
      "id": "skill_XXXX",
      "effectiveness": "low|medium|high",
      "description": "optional updated description",
      "code": "optional: full replacement bash snippet"
    }}
  ]
}}
"""

        try:
            response = text_completion(prompt, self.model_name, "HarnessEvolver_Skills")
            recommendations = self._parse_json_response(response)
            if recommendations is None:
                return {"error": "failed_to_parse_response"}

            result = {"created": [], "updated": [], "analysis": recommendations.get("analysis", "")}

            for spec in recommendations.get("add", []):
                try:
                    entry_id = store.add(
                        path=spec.get("path", "general"),
                        name=spec.get("name", "Unnamed Skill"),
                        summary=spec.get("summary", ""),
                        description=spec.get("description", ""),
                        code=spec.get("code", ""),
                        effectiveness=spec.get("effectiveness", "medium"),
                        importance=spec.get("importance", 3),
                        source="evolved",
                        created_in_task=self._evolved_provenance(),
                    )
                    result["created"].append(entry_id)
                    logger.info("Created evolved skill: %s (%s)", entry_id, spec.get("name"))
                except Exception as e:
                    logger.error("Failed to create skill %s: %s", spec.get("name"), e)

            for upd in recommendations.get("update", []):
                sid = upd.get("id")
                if not sid:
                    continue
                try:
                    fields = {k: v for k, v in upd.items() if k != "id" and v}
                    if fields:
                        store.update(sid, **fields)
                        result["updated"].append(sid)
                except Exception as e:
                    logger.error("Failed to update skill %s: %s", sid, e)

            return result

        except Exception as e:
            logger.error("Skill evolution failed: %s", e, exc_info=True)
            return {"error": str(e)}

    def _evolve_memory(
        self, trajectories: List[Dict[str, Any]], current_step: int
    ) -> Dict[str, Any]:
        """Lightweight memory curation: fill gaps and rebalance importance."""
        store = self._get_memory_store()
        memory_overview = store.get_tree_overview()

        trajectory_summary = self.prompt_optimizer._format_trajectories_for_analysis(
            trajectories
        )
        recent_edits = self._recent_edits_digest("memory")
        effective_variant = (
            self.memory_prompt_variant
            if self.memory_prompt_variant != "current"
            else self.evolution_prompt_variant
        )
        variant_guidance = load_memory_variant(effective_variant)

        prompt = f"""You are a memory curator for an AI agent working on {self.task_domain}.

Your job: review the agent's memory store and recent trajectories, then recommend targeted improvements.

## Current Memory Overview
{memory_overview}

{recent_edits}
## Recent Trajectories (last {len(trajectories)} steps)
{trajectory_summary}

{variant_guidance}

## Curation Tasks

1. **Fill knowledge gaps**: Add decision-relevant knowledge from the trajectory that is absent from the store.
2. **Improve existing entries**: Replace task narration with a more reusable lesson when the trajectory supports it, and update content that no longer matches observed behavior.
3. **Rebalance importance**: Raise entries likely to affect recurring work and lower entries that no longer help choose actions.

Keep recommendations minimal (max 3-5 changes). Do NOT duplicate what the agent already stored.

## Output Format

Respond with ONLY a JSON object (no markdown fences):
{{
  "analysis": "Brief summary of memory state",
  "add": [
    {{
      "path": "category/subcategory",
      "title": "string",
      "content": "string",
      "importance": 3
    }}
  ],
  "update": [
    {{
      "id": "mem_XXXX",
      "content": "optional updated content",
      "importance": 2
    }}
  ]
}}
"""

        try:
            response = text_completion(prompt, self.model_name, "HarnessEvolver_Memory")
            recommendations = self._parse_json_response(response)
            if recommendations is None:
                return {"error": "failed_to_parse_response"}

            result = {"created": [], "updated": [], "analysis": recommendations.get("analysis", "")}

            for spec in recommendations.get("add", []):
                try:
                    entry_id = store.add(
                        path=spec.get("path", "general"),
                        title=spec.get("title", "Untitled"),
                        content=spec.get("content", ""),
                        importance=spec.get("importance", 3),
                        source="evolved",
                        created_in_task=self._evolved_provenance(),
                    )
                    result["created"].append(entry_id)
                    logger.info("Created evolved memory: %s (%s)", entry_id, spec.get("title"))
                except Exception as e:
                    logger.error("Failed to create memory: %s", e)

            for upd in recommendations.get("update", []):
                mid = upd.get("id")
                if not mid:
                    continue
                try:
                    fields = {k: v for k, v in upd.items() if k != "id" and v is not None}
                    if fields:
                        store.update(mid, **fields)
                        result["updated"].append(mid)
                except Exception as e:
                    logger.error("Failed to update memory %s: %s", mid, e)

            return result

        except Exception as e:
            logger.error("Memory evolution failed: %s", e, exc_info=True)
            return {"error": str(e)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _parse_json_response(self, response: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM response, handling markdown fences."""
        text = response.strip()
        # Strip markdown code fences
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the response
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.error("Failed to parse JSON from evolution response: %s", text[:200])
            return None

    def _save_evolution_log(self, current_step: int, results: Dict[str, Any]):
        """Persist evolution log entry to cache."""
        from continual_harness.cache import get_cache_path

        entry = {
            "generation": self.generation,
            "step": current_step,
            "task": getattr(self, "_evolving_task", "") or "",
            "timestamp": datetime.now().isoformat(),
            "prompt_rewritten": results.get("prompt", {}).get("rewritten", False),
            "subagents_created": results.get("subagents", {}).get("created", []),
            "subagents_updated": results.get("subagents", {}).get("updated", []),
            "subagents_retired": results.get("subagents", {}).get("retired", []),
            "skills_created": results.get("skills", {}).get("created", []),
            "skills_updated": results.get("skills", {}).get("updated", []),
            "memory_created": results.get("memory", {}).get("created", []),
            "memory_updated": results.get("memory", {}).get("updated", []),
        }

        # Append store counts
        try:
            entry["store_counts"] = {
                "memory": len(self._get_memory_store()._entries),
                "skills": len(self._get_skill_store()._entries),
                "subagents": len(self._get_subagent_store()._entries),
            }
        except Exception:
            pass

        self.evolution_log.append(entry)

        try:
            log_file = get_cache_path("evolution_log.jsonl")
            with open(log_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
            logger.info("Saved evolution log: generation=%d step=%d", self.generation, current_step)
        except Exception as e:
            logger.error("Failed to save evolution log: %s", e)


def create_harness_evolver(
    model_name: str,
    run_data_manager,
    base_prompt_path: str = CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH,
    system_prompt_path: str = CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH,
    initial_prompt_override: str | None = None,
    task_domain: str | None = None,
) -> HarnessEvolver:
    """Factory function to create a HarnessEvolver instance."""
    return HarnessEvolver(
        model_name, run_data_manager, base_prompt_path, system_prompt_path,
        initial_prompt_override=initial_prompt_override,
        task_domain=task_domain,
    )
