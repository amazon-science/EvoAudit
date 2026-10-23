"""SafeEvoBench benchmark specifics injected into the Continual Harness framework.

The framework owns the evolution tools, the agent loop, and the prompt compiler.
A benchmark only provides: its ``bash`` / ``task_complete`` tool *descriptions*
(workspace-flavored), the cache base for its runs, the domain label, and the set
of workspace files to snapshot for evaluation. ``make_spec`` packages these into
a :class:`continual_harness.config.BenchmarkSpec`.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from continual_harness.config import BenchmarkSpec

logger = logging.getLogger(__name__)

# SafeEvoBench's workspace-flavored bash + task_complete declarations.
SAFEEVO_BASH_TOOL = {
    "name": "bash",
    "description": (
        "Execute a bash command in the operations workspace. "
        "The command runs in a Linux environment with workspace files "
        "at /workspace/ including service repos, monitoring configs, tickets, "
        "documentation, logs, and automation scripts. Returns stdout, stderr, "
        "and return code."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "command": {
                "type_": "STRING",
                "description": "The bash command to execute",
            },
        },
        "required": ["command"],
    },
}

SAFEEVO_TASK_COMPLETE_TOOL = {
    "name": "task_complete",
    "description": (
        "Signal that the task is complete. Call this when you have finished "
        "the assigned task or determined that no further action is needed."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "reason": {
                "type_": "STRING",
                "description": "Explanation of why the task is complete and what was accomplished",
            },
        },
        "required": ["reason"],
    },
}

# Fallback snapshot paths if a group declares none. SafeEvoBench groups always ship
# their own evaluation/snapshot_paths.json, so this is a minimal safety net.
DEFAULT_SNAPSHOT_PATHS: List[str] = []


def load_snapshot_paths(group_dir: Optional[str]) -> List[str]:
    """Return the workspace files to snapshot for evaluation.

    Per-group: if ``<group_dir>/evaluation/snapshot_paths.json`` exists (a JSON
    list of relative paths), use it. Every SafeEvoBench group ships one, so the
    empty default is only a fallback."""
    if group_dir:
        path = Path(group_dir) / "evaluation" / "snapshot_paths.json"
        if path.exists():
            try:
                paths = json.load(open(path))
                if isinstance(paths, list) and all(isinstance(p, str) for p in paths):
                    return paths
                logger.warning("snapshot_paths.json is not a list[str]; using defaults: %s", path)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Could not load %s (%s); using default snapshot paths", path, e)
    return DEFAULT_SNAPSHOT_PATHS


def make_spec(dataset_role: str, domain: str = "DevOps/SRE",
              group_dir: Optional[str] = None,
              cache_base: str = ".safeevo_cache") -> BenchmarkSpec:
    """Build the SafeEvoBench BenchmarkSpec. ``dataset_role`` comes from the group's
    tasks.json ``system_prompt``; if empty, the agent falls back to it itself.
    ``group_dir`` (when given) enables the per-group snapshot-path override.
    ``cache_base`` is the directory where per-run output folders are written
    (default ``.safeevo_cache``); override it to log runs elsewhere."""
    return BenchmarkSpec(
        name="safeevobench",
        base_tools=[SAFEEVO_BASH_TOOL, SAFEEVO_TASK_COMPLETE_TOOL],
        dataset_role=dataset_role,
        cache_base=cache_base,
        snapshot_paths=load_snapshot_paths(group_dir),
        domain=domain,
    )
