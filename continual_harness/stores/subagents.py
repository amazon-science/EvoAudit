# Portions adapted from sethkarten/continual-harness (MIT License,
# Copyright (c) 2026 Seth Karten et al.), modified. See THIRD-PARTY-NOTICES.txt.
"""
Subagent store — persistent subagent registry for PokeAgent.

Inherits from BaseStore; subagent entries describe executable configs
for custom (evolved or orchestrator-created) subagents, plus read-only
records for built-in subagents so they appear in the prompt registry.
"""

import logging
from dataclasses import dataclass, field
from typing import List, Optional

from continual_harness.stores.base_store import BaseStore, _INTERNAL_FIELDS

logger = logging.getLogger(__name__)

MAX_INSTRUCTIONS_LEN = 12_000
MAX_DIRECTIVE_LEN = 12_000

_SUBAGENT_DISPLAY_EXCLUDE = _INTERNAL_FIELDS | frozenset({
    "system_instructions",
    "directive",
})


@dataclass
class SubagentEntry:
    """A single entry in the subagent registry."""

    id: str = ""
    path: str = "custom"
    name: str = ""
    description: str = ""
    handler_type: str = "looping"  # "one_step" | "looping"
    max_turns: int = 25
    available_tools: List[str] = field(default_factory=list)
    system_instructions: str = ""
    directive: str = ""
    return_condition: str = ""
    importance: int = 3
    source: str = "orchestrator"  # "built-in" | "evolved" | "orchestrator"
    created_in_task: str = ""  # task id this subagent was registered during (provenance for transfer analysis)
    is_builtin: bool = False
    created_at: str = None  # type: ignore[assignment]
    updated_at: str = None  # type: ignore[assignment]
    mutation_history: List[dict] = field(default_factory=list)
    title: str = ""  # alias for name — used by BaseStore tree overview

    def __post_init__(self):
        if self.created_at is None:
            from datetime import datetime

            self.created_at = datetime.now().isoformat()
        if self.updated_at is None:
            self.updated_at = self.created_at
        if not self.title and self.name:
            self.title = self.name
        elif self.title and not self.name:
            self.name = self.title


BUILTIN_SUBAGENT_CONFIGS: List[dict] = [
    {
        "name": "explore",
        "description": "Explore filesystem structure, find files by pattern, report directory layout. Use for discovering workspace contents, locating specific files, or mapping project structure.",
        "handler_type": "looping",
        "max_turns": 15,
        "system_instructions": (
            "You are a filesystem exploration subagent. Your job is to navigate directories, "
            "find files matching patterns, and report what you discover. Be systematic: start "
            "broad (ls directories) then go deep into relevant areas. Report findings as a "
            "structured list with paths, file types, and brief descriptions of what each contains. "
            "Use grep to search file contents when looking for specific patterns. "
            "Call task_complete with your structured findings when done."
        ),
        "is_builtin": True,
        "source": "built-in",
        "importance": 5,
    },
    {
        "name": "analyze_file",
        "description": "Read and analyze a specific file's content in depth. Use for understanding code, configs, data files, or documentation that requires careful reading.",
        "handler_type": "looping",
        "max_turns": 10,
        "system_instructions": (
            "You are a file analysis subagent. Read the target file carefully and provide "
            "a thorough analysis: structure, key content, patterns, potential issues, and "
            "relevant details. For code: describe what it does, key functions, dependencies. "
            "For configs: describe settings, their purpose, any unusual values. "
            "For data: describe schema, row counts, value ranges, anomalies. "
            "Call task_complete with your analysis when done."
        ),
        "is_builtin": True,
        "source": "built-in",
        "importance": 5,
    },
    {
        "name": "run_and_report",
        "description": "Execute a command or script and summarize its output. Use for running health checks, test suites, scans, or any command whose output needs interpretation.",
        "handler_type": "looping",
        "max_turns": 10,
        "system_instructions": (
            "You are an execution and reporting subagent. Run the specified command or script, "
            "capture its output, and provide a structured summary. Include: exit code, key "
            "findings from stdout/stderr, any errors or warnings, and a brief interpretation "
            "of what the results mean. If the output is long, focus on the most important parts. "
            "Call task_complete with your structured report when done."
        ),
        "is_builtin": True,
        "source": "built-in",
        "importance": 5,
    },
    {
        "name": "investigate",
        "description": "Deep investigation of a question across multiple files and sources. Use for research tasks that require cross-referencing logs, configs, code, and documentation.",
        "handler_type": "looping",
        "max_turns": 20,
        "system_instructions": (
            "You are an investigation subagent. Research the given question thoroughly by "
            "reading relevant files, checking logs, examining configs, and cross-referencing "
            "multiple sources. Build evidence for your conclusions. Report: what you found, "
            "where you found it (file paths + line numbers), how different sources relate, "
            "and your conclusion with confidence level. If something is ambiguous, note it. "
            "Check list_memory for any prior knowledge that might help. "
            "Call task_complete with your investigation report when done."
        ),
        "is_builtin": True,
        "source": "built-in",
        "importance": 5,
    },
]


def _validate_char_caps(**fields) -> None:
    """Raise ValueError if system_instructions or directive exceed caps."""
    si = fields.get("system_instructions")
    if si is not None and len(si) > MAX_INSTRUCTIONS_LEN:
        raise ValueError(
            f"system_instructions exceeds {MAX_INSTRUCTIONS_LEN} char cap "
            f"({len(si)} chars)"
        )
    directive = fields.get("directive")
    if directive is not None and len(directive) > MAX_DIRECTIVE_LEN:
        raise ValueError(
            f"directive exceeds {MAX_DIRECTIVE_LEN} char cap "
            f"({len(directive)} chars)"
        )


class SubagentStore(BaseStore[SubagentEntry]):
    """Persistent subagent registry."""

    file_name = "subagents.json"
    id_prefix = "sa_"
    store_label = "SUBAGENT REGISTRY"
    empty_message = "No subagents registered yet."
    entry_class = SubagentEntry

    def __init__(self, cache_dir: Optional[str] = None):
        super().__init__(cache_dir)
        self.load()

    def load(self) -> None:
        super().load()
        self._seed_builtins()

    def _seed_builtins(self) -> None:
        """Populate built-in entries if none exist yet.

        Skipped entirely when ``EXCLUDE_BUILTIN_SUBAGENTS=1`` so the registry
        starts empty and the model must create subagents from scratch.
        """
        import os
        if os.environ.get("EXCLUDE_BUILTIN_SUBAGENTS") == "1":
            logger.info("EXCLUDE_BUILTIN_SUBAGENTS is set — skipping built-in seeding")
            return

        has_builtins = any(
            getattr(e, "is_builtin", False)
            for e in self.entries.values()
        )
        if has_builtins:
            return

        for cfg in BUILTIN_SUBAGENT_CONFIGS:
            self.add(**cfg)
        logger.info(
            "Seeded %d built-in subagent entries", len(BUILTIN_SUBAGENT_CONFIGS)
        )

    def add(self, **fields) -> str:
        _validate_char_caps(**fields)
        return super().add(**fields)

    def update(self, entry_id: str, **fields) -> bool:
        _validate_char_caps(**fields)
        return super().update(entry_id, **fields)

    def remove(self, entry_id: str) -> bool:
        entry = self.entries.get(entry_id)
        if entry is not None and getattr(entry, "is_builtin", False):
            logger.warning("Cannot delete built-in subagent %s", entry_id)
            return False
        return super().remove(entry_id)

    def to_display_dict(self, entry: SubagentEntry) -> dict:
        from dataclasses import asdict

        d = asdict(entry)
        for field_name in _SUBAGENT_DISPLAY_EXCLUDE:
            d.pop(field_name, None)
        return d

    def _deserialize_entry(self, entry_dict: dict) -> SubagentEntry:
        entry_dict.setdefault("mutation_history", [])
        entry_dict.setdefault("source", "orchestrator")
        entry_dict.setdefault("handler_type", "looping")
        entry_dict.setdefault("max_turns", 25)
        entry_dict.setdefault("available_tools", [])
        entry_dict.setdefault("system_instructions", "")
        entry_dict.setdefault("directive", "")
        entry_dict.setdefault("return_condition", "")
        entry_dict.setdefault("importance", 3)
        entry_dict.setdefault("is_builtin", False)
        if entry_dict.get("name") and not entry_dict.get("title"):
            entry_dict["title"] = entry_dict["name"]
        elif entry_dict.get("title") and not entry_dict.get("name"):
            entry_dict["name"] = entry_dict["title"]
        return SubagentEntry(**entry_dict)


# Global singleton
_subagent_store: Optional[SubagentStore] = None


def get_subagent_store() -> SubagentStore:
    """Get or create the global SubagentStore instance."""
    global _subagent_store
    if _subagent_store is None:
        _subagent_store = SubagentStore()
    return _subagent_store
