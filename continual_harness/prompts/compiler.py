"""System-prompt compiler for the Continual Harness.

Assembles the system prompt from modular pieces so it reflects exactly the
enabled tool families:

  1. the standard base policy (or an evolved rewrite of it, if provided),
  2. the dataset/task-group role block (injected by the benchmark),
  3. for each enabled family (in canonical order), the family's prompt fragment
     — a family-level description plus a per-tool description and usage example.

A tool's explanation appears in the prompt iff its family is enabled, so base
runs (no evolution) get a lean prompt and richer configurations get exactly the
guidance for the tools they actually have.

The system prompt deliberately does NOT list the *contents* of the memory /
skills / subagents stores. Accumulated artifacts are reachable ONLY through the
tools (``list_memory`` / ``read_memory`` / ``list_skills`` / ``get_skill`` /
``list_subagents``). This keeps a clean separation between prompt-level guidance
and evolved knowledge, and makes every reuse of an accumulated artifact an
explicit, logged tool call (which the transfer analysis relies on).
"""

import os
from pathlib import Path
from typing import List, Optional

_PROMPTS_DIR = Path(__file__).parent
_FRAGMENTS_DIR = _PROMPTS_DIR / "fragments"
_BASE_POLICY_PATH = _PROMPTS_DIR / "base_policy.md"

# Families rendered in this order when enabled.
_FRAGMENT_ORDER = ("planning", "memory", "skills", "subagents", "evolve")

_DEFAULT_BASE = (
    "You are an autonomous AI assistant. Use bash to complete the task, work "
    "methodically, verify your work, and call task_complete when done."
)


def load_base_policy() -> str:
    """Read the recognition-neutral, family-agnostic core policy."""
    try:
        return _BASE_POLICY_PATH.read_text()
    except FileNotFoundError:
        return _DEFAULT_BASE


def load_fragment(family_key: str) -> str:
    """Read a family's prompt fragment (family description + per-tool examples)."""
    path = _FRAGMENTS_DIR / f"{family_key}.md"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return ""


def load_evolution_variant(mechanism: str, variant: str) -> str:
    """Read one mechanism's conditional evolution-prompt supplement."""
    if variant == "current":
        return ""
    path = _FRAGMENTS_DIR / f"{mechanism}_variants" / f"{variant}.md"
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return ""


def load_memory_variant(variant: str) -> str:
    """Backward-compatible loader for voluntary-memory ablations."""
    return load_evolution_variant("memory", variant)


def _render_subagents_fragment(text: str) -> str:
    """Resolve the built-in-types markers in the subagents fragment against the actual
    runtime registry. When EXCLUDE_BUILTIN_SUBAGENTS=1 the registry starts empty, so the
    prompt must NOT advertise built-in types (explore/investigate/…) that don't exist —
    otherwise the model spawns a phantom type and just burns a step on an error. We keep
    the <!--BUILTIN_TYPES--> lines only when built-ins are present, and the <!--NO_BUILTINS-->
    line only when they're excluded."""
    exclude = os.environ.get("EXCLUDE_BUILTIN_SUBAGENTS") == "1"
    keep, drop = ("<!--NO_BUILTINS-->", "<!--BUILTIN_TYPES-->") if exclude \
        else ("<!--BUILTIN_TYPES-->", "<!--NO_BUILTINS-->")
    out = []
    for line in text.splitlines():
        if drop in line:
            continue
        out.append(line.replace(keep, ""))
    return "\n".join(out)


def build_system_prompt(
    *,
    dataset_role: str,
    enabled_families: List[str],
    evolved_base: Optional[str] = None,
    memory_mode: str = "pull",
    memory_prompt_variant: str = "current",
    evolution_prompt_variant: str = "current",
) -> str:
    """Compile the full system prompt.

    Args:
        dataset_role: benchmark/task-group role text (the "what you are here").
        enabled_families: family keys that are on (order-independent; rendered in
            canonical order).
        evolved_base: if set, replaces the standard base policy (an evolve_harness
            rewrite).

    The contents of the memory/skills/subagents stores are intentionally NOT
    rendered here — they are reachable only via the tools, so the agent must
    explicitly retrieve an accumulated artifact to use it.
    """
    enabled = set(enabled_families)
    parts: List[str] = [evolved_base or load_base_policy()]

    if dataset_role:
        parts.append(f"\n# Workspace Context\n\n{dataset_role}")

    # Tool guidance: one fragment per enabled family, canonical order. Render a
    # "# Your Tools" header only if at least one family is enabled.
    # In push-memory mode the pull tools (search/read) are suppressed and prior memory is
    # auto-injected instead, so use the push variant of the memory fragment (save-only guidance).
    def _frag(k):
        if k == "memory" and memory_mode == "push":
            return load_fragment("memory_push") or load_fragment("memory")
        if k == "subagents":
            return _render_subagents_fragment(load_fragment("subagents"))
        return load_fragment(k)
    fragments = []
    for key in _FRAGMENT_ORDER:
        if key not in enabled:
            continue
        fragment = _frag(key)
        if fragment:
            fragments.append(fragment)
        if key == "memory" and memory_mode == "pull":
            effective_memory_variant = (
                memory_prompt_variant
                if memory_prompt_variant != "current"
                else evolution_prompt_variant
            )
            memory_variant = load_memory_variant(effective_memory_variant)
            if memory_variant:
                fragments.append(memory_variant)
        elif key in {"skills", "subagents", "evolve"}:
            variant = load_evolution_variant(key, evolution_prompt_variant)
            if variant:
                fragments.append(variant)
    if fragments:
        parts.append("\n# Your Tools\n\nBeyond `bash` and `task_complete`, you have:")
        parts.extend("\n" + f for f in fragments)
        # Only when BOTH memory and skills are available is the distinction
        # ambiguous (both can hold text) — clarify it then, not otherwise.
        if {"memory", "skills"} <= enabled:
            parts.append(
                "\n**Memory vs. skills:** memory holds *facts* — things that are true about the "
                "workspace, policies, or system state, which you recall to inform a decision. A "
                "skill holds a *procedure* — a repeatable how-to you follow (and whose code you "
                "may run via bash). If it's a fact, save it as memory; if it's a way of doing "
                "something, save it as a skill."
            )

    return "\n".join(parts)
