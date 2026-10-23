"""Configuration objects for the Continual Harness.

``HarnessConfig`` carries the independently enabled tool families (memory /
skills / subagents / evolve / planning), harness-controlled meta features, and
context-management knobs.

``BenchmarkSpec`` carries everything a benchmark injects into the framework so
the agent itself stays dataset-agnostic: the ``bash`` / ``task_complete`` tool
declarations the benchmark wants, the dataset role text, the cache base dir, and
the list of workspace files to snapshot for evaluation.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Order families are assembled / rendered in.
FAMILY_ORDER = ("planning", "memory", "skills", "subagents", "evolve")
META_FEATURE_ORDER = ("meta_memory", "meta_skills", "meta_prompt")
MEMORY_PROMPT_VARIANTS = (
    "current",
    "generalize",
    "generalize_urgent",
    "generalize_urgent_trust",
)
EVOLUTION_PROMPT_VARIANTS = ("current", "generalize", "operative")


@dataclass
class HarnessConfig:
    """Per-family enable flags + context-management knobs."""

    # Evolution tool families (each independently toggleable).
    memory: bool = False
    skills: bool = False
    subagents: bool = False
    evolve: bool = False
    planning: bool = False
    # Optional memory-only prompt supplement used by prompt-ablation studies.
    # "current" preserves the historical compiled prompt exactly.
    memory_prompt_variant: str = "current"
    # Cross-mechanism prompt treatment. It is rendered only for enabled
    # mechanisms; the memory-specific setting above takes precedence when set.
    evolution_prompt_variant: str = "current"

    # Harness-controlled post-task features. Unlike the voluntary families above,
    # these expose no read/write/trigger tools to the primary agent.
    meta_memory: bool = False
    meta_skills: bool = False
    meta_prompt: bool = False
    # None means "use the same model as the primary agent".
    meta_model: Optional[str] = None

    # Run/loop knobs.
    max_steps: int = 100
    # How many recent trajectory steps each evolution pass analyzes. Kept small: the
    # optimizer only needs recent behavior to spot patterns, and every pass re-sends this
    # window to the LLM, so a large value inflates evolve latency/cost with little signal
    # gain. Paired with the recent-edits digest (see HarnessEvolver), 15 is ample.
    evolution_window: int = 15
    # How many recent evolution generations of the agent's OWN edits to show each pass
    # (so it sees "what I already changed" and doesn't re-propose the same thing).
    evolution_edit_history: int = 3
    refresh_prompt_between_tasks: bool = False
    reset_context_between_tasks: bool = False
    # Reset the sandbox WORKSPACE to its pristine baked state between tasks (the container is
    # recreated), while the host-side evolution stores persist. This makes the evolution store
    # the ONLY channel through which one task can influence the next — no fixture-state carryover.
    # Used for the store-only ("airtight attribution") pair arm so a source->target delta is
    # attributable to disposition drift, not to leaked workspace state. Default False keeps the
    # historical persistent-workspace behavior (the ecological "full longitudinal" arm).
    reset_workspace_between_tasks: bool = False

    # Abort the run after this many CONSECUTIVE sandbox connection failures (a dead
    # executor backend returns returncode -1 / "Connection error: ..." for every
    # command). Without this the agent flails across every remaining task with a
    # dead container, poisoning the whole run. A single successful command resets
    # the streak, so transient blips are tolerated. 0 disables the guard.
    max_exec_connection_errors: int = 8

    # Context-window management.
    max_tool_result_chars: Optional[int] = None
    context_limit: Optional[int] = None
    context_budget_frac: float = 0.75
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        if self.memory_prompt_variant not in MEMORY_PROMPT_VARIANTS:
            raise ValueError(
                "Unknown memory_prompt_variant "
                f"{self.memory_prompt_variant!r}; expected one of "
                f"{', '.join(MEMORY_PROMPT_VARIANTS)}"
            )
        if self.evolution_prompt_variant not in EVOLUTION_PROMPT_VARIANTS:
            raise ValueError(
                "Unknown evolution_prompt_variant "
                f"{self.evolution_prompt_variant!r}; expected one of "
                f"{', '.join(EVOLUTION_PROMPT_VARIANTS)}"
            )
        if self.evolution_prompt_variant != "current" and not self.any_evolution:
            raise ValueError(
                "evolution_prompt_variant requires at least one evolution "
                "mechanism to be enabled"
            )
        conflicts = []
        if self.memory and self.meta_memory:
            conflicts.append("memory and meta_memory")
        if self.skills and self.meta_skills:
            conflicts.append("skills and meta_skills")
        if self.evolve and self.meta_prompt:
            conflicts.append("evolve and meta_prompt")
        if conflicts:
            raise ValueError(
                "Voluntary and meta variants are mutually exclusive: "
                + ", ".join(conflicts)
            )

    def enabled_families(self) -> List[str]:
        """Family keys that are on, in canonical render/assembly order."""
        flags = {
            "memory": self.memory,
            "skills": self.skills,
            "subagents": self.subagents,
            "evolve": self.evolve,
            "planning": self.planning,
        }
        return [k for k in FAMILY_ORDER if flags[k]]

    def enabled_meta_features(self) -> List[str]:
        """Harness-controlled post-task features in execution order."""
        flags = {
            "meta_memory": self.meta_memory,
            "meta_skills": self.meta_skills,
            "meta_prompt": self.meta_prompt,
        }
        return [k for k in META_FEATURE_ORDER if flags[k]]

    @property
    def any_evolution(self) -> bool:
        """True if any non-planning voluntary or meta feature is enabled."""
        return bool(
            self.memory
            or self.skills
            or self.subagents
            or self.evolve
            or self.enabled_meta_features()
        )

    @classmethod
    def from_flags(
        cls,
        *,
        enable_memory: bool = False,
        enable_skills: bool = False,
        enable_subagents: bool = False,
        enable_evolve: bool = False,
        enable_meta_memory: bool = False,
        enable_meta_skills: bool = False,
        enable_meta_prompt: bool = False,
        enable_planning: bool = False,
        **kwargs: Any,
    ) -> "HarnessConfig":
        """Build from independent CLI-style family and meta-feature flags."""
        return cls(
            memory=enable_memory,
            skills=enable_skills,
            subagents=enable_subagents,
            evolve=enable_evolve,
            meta_memory=enable_meta_memory,
            meta_skills=enable_meta_skills,
            meta_prompt=enable_meta_prompt,
            planning=enable_planning,
            **kwargs,
        )


@dataclass
class BenchmarkSpec:
    """What a benchmark injects so the framework stays dataset-agnostic."""

    name: str
    # The benchmark's bash + task_complete tool declarations (workspace-flavored).
    base_tools: List[dict]
    # Dataset role / workspace-context text appended to the base policy.
    dataset_role: str
    # Cache base dir for this benchmark's runs (e.g. ".essr_cache").
    cache_base: str = ".continual_cache"
    # Workspace files to snapshot from the container after each task (for eval).
    snapshot_paths: List[str] = field(default_factory=list)
    # Optional domain label passed to the evolver.
    domain: str = "operational tasks"
