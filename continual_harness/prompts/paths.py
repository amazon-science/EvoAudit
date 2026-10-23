"""Prompt path constants and helpers for the Continual Harness evolver.

The evolver's PromptOptimizer needs an initial base/system prompt to seed its
rewrites from. It uses the framework's standard base policy.
"""

import os
from pathlib import Path

# Default task domain name (overridable via the TASK_DOMAIN env var).
GAME_NAME = os.environ.get("TASK_DOMAIN", "operational tasks")

# The framework's standard base policy seeds the evolver's prompt rewriting.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BASE_POLICY_REL = "continual_harness/prompts/base_policy.md"

CONTINUAL_HARNESS_BASE_ORCHESTRATOR_POLICY_PATH = _BASE_POLICY_REL
CONTINUAL_HARNESS_SYSTEM_PROMPT_PATH = _BASE_POLICY_REL


def render_prompt(content: str) -> str:
    """Substitute {game_name} in prompt content with the task domain."""
    return content.replace("{game_name}", GAME_NAME)


def resolve_repo_path(relative_path: str) -> Path:
    """Resolve a repository-root-relative path to an absolute Path."""
    p = Path(relative_path)
    return p if p.is_absolute() else _REPO_ROOT / relative_path
