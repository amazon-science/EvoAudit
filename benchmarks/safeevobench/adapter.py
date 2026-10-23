"""Adapter: build a ContinualAgent configured for the SafeEvoBench benchmark.

This is the seam between the framework and the SafeEvoBench dataset. It reads the
group's dataset role, maps CLI-style flags onto a HarnessConfig, builds the
SafeEvoBench BenchmarkSpec, and returns a ready ContinualAgent.
"""

import json
from pathlib import Path
from typing import Optional

from benchmarks.safeevobench.tools import make_spec
from continual_harness.agent import ContinualAgent
from continual_harness.config import HarnessConfig


def load_dataset_role(group_dir: str) -> str:
    """Read the group's dataset role from tasks.json (the ``system_prompt`` field)."""
    with open(Path(group_dir) / "tasks.json") as f:
        return json.load(f).get("system_prompt", "")


def load_domain(group_dir: str) -> str:
    """Read the group's domain label from tasks.json (the ``domain`` field).

    Content-agnostic: reads whatever the group declares. DevOps declares "DevOps/SRE"
    so its behavior is unchanged; a new domain (e.g. workspace-acme's
    "Enterprise/Workspace") is labeled correctly in evolution prompts instead of
    inheriting the DevOps default."""
    with open(Path(group_dir) / "tasks.json") as f:
        return json.load(f).get("domain", "DevOps/SRE")


def build_agent(
    *,
    model_name: str,
    sandbox,
    group_dir: str,
    run_name: Optional[str] = None,
    # Independently enabled voluntary families.
    enable_memory: bool = False,
    enable_skills: bool = False,
    enable_subagents: bool = False,
    enable_evolve: bool = False,
    # Harness-controlled post-task features.
    enable_meta_memory: bool = False,
    enable_meta_skills: bool = False,
    enable_meta_prompt: bool = False,
    meta_model: Optional[str] = None,
    enable_planning: bool = False,
    memory_prompt_variant: str = "current",
    evolution_prompt_variant: str = "current",
    # Loop / context knobs.
    max_steps: int = 100,
    evolution_window: int = 15,
    evolution_edit_history: int = 3,
    refresh_prompt_between_tasks: bool = False,
    reset_context_between_tasks: bool = False,
    reset_workspace_between_tasks: bool = False,
    max_tool_result_chars: Optional[int] = None,
    context_limit: Optional[int] = None,
    context_budget_frac: float = 0.75,
    max_output_tokens: int = 4096,
    cache_base: str = ".safeevo_cache",
) -> ContinualAgent:
    """Construct a ContinualAgent for a SafeEvoBench group directory.

    ``cache_base`` is the root directory for per-run output folders (default
    ``.safeevo_cache``); each run lands in ``{cache_base}/{run_name}/``."""
    config = HarnessConfig.from_flags(
        enable_memory=enable_memory,
        enable_skills=enable_skills,
        enable_subagents=enable_subagents,
        enable_evolve=enable_evolve,
        enable_meta_memory=enable_meta_memory,
        enable_meta_skills=enable_meta_skills,
        enable_meta_prompt=enable_meta_prompt,
        enable_planning=enable_planning,
        memory_prompt_variant=memory_prompt_variant,
        evolution_prompt_variant=evolution_prompt_variant,
        meta_model=meta_model,
        max_steps=max_steps,
        evolution_window=evolution_window,
        evolution_edit_history=evolution_edit_history,
        refresh_prompt_between_tasks=refresh_prompt_between_tasks,
        reset_context_between_tasks=reset_context_between_tasks,
        reset_workspace_between_tasks=reset_workspace_between_tasks,
        max_tool_result_chars=max_tool_result_chars,
        context_limit=context_limit,
        context_budget_frac=context_budget_frac,
        max_output_tokens=max_output_tokens,
    )
    spec = make_spec(dataset_role=load_dataset_role(group_dir),
                     domain=load_domain(group_dir), group_dir=group_dir,
                     cache_base=cache_base)
    return ContinualAgent(
        model_name=model_name,
        sandbox=sandbox,
        group_dir=group_dir,
        spec=spec,
        config=config,
        run_name=run_name,
    )
