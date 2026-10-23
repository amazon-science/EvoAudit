"""
Task plan store — persistent per-task planning for the Continual Harness.

A TaskPlanEntry holds the agent's decomposition of a single task: a goal, an
approach narrative, the tools it intends to use, and a list of todo items each
with a resolution status (pending | done | cancelled). The orchestrator creates
one plan per task and maintains it as it works.

Inherits from BaseStore so plans persist to plans.json and appear in the store
tree overview, enabling cross-task analysis of planning behavior.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from continual_harness.stores.base_store import BaseStore

logger = logging.getLogger(__name__)

# Valid todo statuses
TODO_PENDING = "pending"
TODO_DONE = "done"
TODO_CANCELLED = "cancelled"
RESOLVED_STATUSES = frozenset({TODO_DONE, TODO_CANCELLED})


@dataclass
class TaskPlanEntry:
    """A single task plan."""

    id: str = ""
    path: str = "plans"
    task_id: str = ""                       # benchmark task this plan is for
    goal: str = ""                          # one-line goal
    approach: str = ""                      # decomposition narrative / strategy
    tools_to_use: List[str] = field(default_factory=list)  # planned tools + why
    todo_items: List[dict] = field(default_factory=list)   # [{id, description, status, note}]
    status: str = "active"                  # active | completed
    revision_count: int = 0
    importance: int = 3
    created_at: str = None  # type: ignore[assignment]
    updated_at: str = None  # type: ignore[assignment]
    mutation_history: List[dict] = field(default_factory=list)
    title: str = ""                         # alias for BaseStore tree overview (= goal)

    def __post_init__(self):
        if self.created_at is None:
            from datetime import datetime
            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at
        if not self.title and self.goal:
            self.title = self.goal


class TaskPlanStore(BaseStore[TaskPlanEntry]):
    """Persistent store of task plans."""

    file_name = "plans.json"
    id_prefix = "plan_"
    store_label = "TASK PLANS"
    empty_message = "No task plans yet."
    entry_class = TaskPlanEntry

    def __init__(self, cache_dir: Optional[str] = None):
        super().__init__(cache_dir)
        self.load()

    # ------------------------------------------------------------------
    # Plan creation with structured todos
    # ------------------------------------------------------------------

    def create_plan(
        self,
        task_id: str,
        goal: str,
        approach: str,
        tools_to_use: List[str],
        todo_descriptions: List[str],
    ) -> str:
        """Create a plan with todo items assigned sequential ids (t1, t2, ...)."""
        todo_items = [
            {"id": f"t{i + 1}", "description": desc, "status": TODO_PENDING, "note": ""}
            for i, desc in enumerate(todo_descriptions)
        ]
        return self.add(
            task_id=task_id,
            goal=goal,
            approach=approach,
            tools_to_use=list(tools_to_use),
            todo_items=todo_items,
            title=goal,
        )

    # ------------------------------------------------------------------
    # Todo management
    # ------------------------------------------------------------------

    def add_todo(self, plan_id: str, description: str) -> Optional[str]:
        """Append a new pending todo. Returns the new item id, or None if plan missing."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return None
        existing_ids = [t["id"] for t in entry.todo_items]
        # Next id = t{max + 1}
        next_n = 1
        for tid in existing_ids:
            try:
                next_n = max(next_n, int(tid.lstrip("t")) + 1)
            except ValueError:
                continue
        item_id = f"t{next_n}"
        entry.todo_items.append({
            "id": item_id, "description": description,
            "status": TODO_PENDING, "note": "",
        })
        self._touch(plan_id)
        return item_id

    def set_todo_status(
        self, plan_id: str, item_id: str, status: str, note: str = "",
    ) -> bool:
        """Set a todo's status (done/cancelled/pending) with an optional note."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return False
        for item in entry.todo_items:
            if item["id"] == item_id:
                item["status"] = status
                if note:
                    item["note"] = note
                self._touch(plan_id)
                return True
        return False

    def all_todos_resolved(self, plan_id: str) -> bool:
        """True if every todo is done or cancelled (or there are no todos)."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return True
        return all(t["status"] in RESOLVED_STATUSES for t in entry.todo_items)

    def pending_todos(self, plan_id: str) -> List[dict]:
        """Return todos still pending."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return []
        return [t for t in entry.todo_items if t["status"] == TODO_PENDING]

    def record_revision(self, plan_id: str) -> None:
        """Increment the revision counter (called by update_task_plan)."""
        entry = self.entries.get(plan_id)
        if entry is not None:
            entry.revision_count += 1
            self._touch(plan_id)

    def format_plan(self, plan_id: str) -> str:
        """Render the full plan as a readable string (tool result for plan tools)."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return f"Plan {plan_id} not found."
        lines = [
            f"=== Task Plan [{entry.id}] (revision {entry.revision_count}) ===",
            f"Goal: {entry.goal}",
            f"Approach: {entry.approach}",
            f"Tools to use: {', '.join(entry.tools_to_use) if entry.tools_to_use else '(none listed)'}",
            "Todo items:",
        ]
        if not entry.todo_items:
            lines.append("  (none)")
        for t in entry.todo_items:
            marker = {"done": "[x]", "cancelled": "[-]", "pending": "[ ]"}.get(t["status"], "[ ]")
            note = f" — {t['note']}" if t.get("note") else ""
            lines.append(f"  {marker} {t['id']}: {t['description']}{note}")
        return "\n".join(lines)

    def snapshot(self, plan_id: str) -> Optional[dict]:
        """Return a plain-dict snapshot of the plan for logging into task results."""
        entry = self.entries.get(plan_id)
        if entry is None:
            return None
        return {
            "plan_id": entry.id,
            "goal": entry.goal,
            "approach": entry.approach,
            "tools_to_use": list(entry.tools_to_use),
            "todos": [
                {"id": t["id"], "description": t["description"],
                 "status": t["status"], "note": t.get("note", "")}
                for t in entry.todo_items
            ],
            "revision_count": entry.revision_count,
            "status": entry.status,
        }

    def _touch(self, plan_id: str) -> None:
        """Persist after an in-place mutation of an entry's nested fields."""
        from datetime import datetime
        entry = self.entries.get(plan_id)
        if entry is not None:
            entry.updated_at = datetime.now().isoformat()
        self._invalidate_cache()
        self.save()

    def _deserialize_entry(self, entry_dict: dict) -> TaskPlanEntry:
        entry_dict.setdefault("mutation_history", [])
        entry_dict.setdefault("tools_to_use", [])
        entry_dict.setdefault("todo_items", [])
        entry_dict.setdefault("status", "active")
        entry_dict.setdefault("revision_count", 0)
        entry_dict.setdefault("importance", 3)
        if entry_dict.get("goal") and not entry_dict.get("title"):
            entry_dict["title"] = entry_dict["goal"]
        return TaskPlanEntry(**entry_dict)


# Global singleton
_task_plan_store: Optional[TaskPlanStore] = None


def get_task_plan_store() -> TaskPlanStore:
    """Get or create the global TaskPlanStore instance."""
    global _task_plan_store
    if _task_plan_store is None:
        _task_plan_store = TaskPlanStore()
    return _task_plan_store


def reset_task_plan_store() -> None:
    """Reset the singleton (mainly for tests / fresh runs)."""
    global _task_plan_store
    _task_plan_store = None
