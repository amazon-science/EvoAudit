"""Compatibility exports for the shared SafeEvoBench judge contract."""

from SafeEvoBench.evaluation_contract import (
    build_judge_prompt,
    build_judge_prompt_parts,
)

__all__ = ["build_judge_prompt", "build_judge_prompt_parts"]
