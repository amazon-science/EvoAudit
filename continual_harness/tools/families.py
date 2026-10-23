"""Evolution tool families for the Continual Harness.

Each family is a coherent group of tools toggled together by a single
``HarnessConfig`` flag (a ``save`` with no ``read`` is useless). A family
carries:
  - ``key``: the config flag name (memory/skills/subagents/evolve/planning),
  - ``description``: a family-level blurb for the compiled system prompt,
  - ``tools``: the core tool declarations that belong to it,
  - ``orchestrator_only``: tools given to the top-level agent but withheld from
    spawned subagents (subagents get read-only memory/skills, no nesting).

The prompt compiler (Phase 3) renders, for each enabled family, the family
description followed by each tool's own description + usage example.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from continual_harness.tools import core_registry as C


@dataclass(frozen=True)
class ToolFamily:
    key: str
    title: str
    description: str
    tools: List[dict]
    # Tools in this family that subagents should NOT receive (orchestrator-only).
    orchestrator_only: frozenset = field(default_factory=frozenset)


MEMORY = ToolFamily(
    key="memory",
    title="Memory",
    description=(
        "Long-term memory persists lessons and observations across tasks. List it at the "
        "start of a task and read the entries that look relevant to reuse prior knowledge; "
        "save durable insights as you discover them."
    ),
    tools=[C.SAVE_MEMORY_TOOL, C.READ_MEMORY_TOOL, C.LIST_MEMORY_TOOL],
)

SKILLS = ToolFamily(
    key="skills",
    title="Skills",
    description=(
        "Skills are reusable workflows you save across tasks — the steps that work for a "
        "recurring kind of problem, optionally with a code snippet. List them before starting "
        "to find one that applies, retrieve its workflow with get_skill (then follow it / run "
        "its code via bash) instead of re-deriving it, and save a new skill when you work out "
        "something worth repeating. Saving is cheap — even a short procedure is worth keeping; "
        "the payoff compounds across the recurring work."
    ),
    tools=[C.SAVE_SKILL_TOOL, C.GET_SKILL_TOOL, C.LIST_SKILLS_TOOL],
)

SUBAGENTS = ToolFamily(
    key="subagents",
    title="Subagents",
    description=(
        "Subagents are focused helpers you can delegate sub-problems to, keeping your "
        "own context clean. List available types, spawn one for a self-contained "
        "sub-task, or register a new specialist type when none fits — registering is "
        "cheap and pays off across future tasks."
    ),
    tools=[
        C.SPAWN_SUBAGENT_TOOL,
        C.REGISTER_SUBAGENT_TOOL,
        C.LIST_SUBAGENTS_TOOL,
        C.ASK_ORCHESTRATOR_TOOL,
    ],
    # ask_orchestrator is a subagent->parent tool; spawn/register/list are
    # orchestrator-only (subagents don't nest or manage the registry).
    orchestrator_only=frozenset(
        {"spawn_subagent", "register_subagent", "list_subagents"}
    ),
)

EVOLVE = ToolFamily(
    key="evolve",
    title="Evolve",
    description=(
        "evolve_harness runs a reflection pass over your recent trajectory and "
        "consolidates what you learned into your prompt, skills, memory, and subagent "
        "types. Call it at a natural break — near the end of a task or between tasks — "
        "once you have something worth keeping."
    ),
    tools=[C.EVOLVE_HARNESS_TOOL],
)

PLANNING = ToolFamily(
    key="planning",
    title="Planning",
    description=(
        "Before acting, decompose the task into a structured plan (goal, approach, "
        "tools, todo items) and maintain it as you go. You can only finish once every "
        "todo is resolved — completing or cancelling (with a reason) each one."
    ),
    tools=[
        C.CREATE_TASK_PLAN_TOOL,
        C.UPDATE_TASK_PLAN_TOOL,
        C.ADD_TODO_ITEM_TOOL,
        C.COMPLETE_TODO_ITEM_TOOL,
        C.CANCEL_TODO_ITEM_TOOL,
        C.LIST_TODO_ITEMS_TOOL,
    ],
)

# Registry of all families, keyed by config flag.
FAMILIES: Dict[str, ToolFamily] = {
    f.key: f for f in (MEMORY, SKILLS, SUBAGENTS, EVOLVE, PLANNING)
}

# Tool names that may only be invoked after a plan exists (Gate 1), derived from
# every family except planning itself plus task_complete. The agent intersects
# this with the tools actually enabled.
ACTION_TOOL_NAMES = frozenset(
    {"task_complete"}
    | {t["name"] for fam in (MEMORY, SKILLS, SUBAGENTS, EVOLVE) for t in fam.tools}
    - {"read_memory", "list_memory", "list_skills", "list_subagents", "ask_orchestrator"}
)


def tools_for(enabled_keys) -> List[dict]:
    """Return the concatenated tool declarations for the enabled family keys."""
    out: List[dict] = []
    for key in enabled_keys:
        fam = FAMILIES.get(key)
        if fam:
            out.extend(fam.tools)
    return out


def subagent_tools_for(enabled_keys) -> List[dict]:
    """Return tools a spawned subagent receives: enabled families minus
    orchestrator-only tools (no nesting, no registry management, no planning)."""
    out: List[dict] = []
    for key in enabled_keys:
        if key == "planning":
            continue
        fam = FAMILIES.get(key)
        if not fam:
            continue
        for t in fam.tools:
            if t["name"] not in fam.orchestrator_only:
                out.append(t)
    return out
