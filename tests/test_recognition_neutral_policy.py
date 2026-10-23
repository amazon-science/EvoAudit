from pathlib import Path

import pytest

from benchmarks.safeevobench.tools import SAFEEVO_BASH_TOOL, make_spec
from continual_harness.config import HarnessConfig
from continual_harness.prompts.compiler import build_system_prompt, load_base_policy

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_recognition_neutral_policy_is_the_only_live_policy():
    policy = load_base_policy()
    assert "# Operating Standard" in policy
    assert "Respect controls" in policy
    assert "How You're Rewarded" not in policy
    assert "explicitly rewarded" not in policy
    assert not (
        REPO_ROOT / "continual_harness" / "prompts" / "base_policy_neutral.md"
    ).exists()

    compiled = build_system_prompt(
        dataset_role="Operate the workspace.",
        enabled_families=[],
    )
    assert compiled.startswith(policy)


def test_framing_is_not_a_configurable_option():
    config = HarnessConfig()
    assert not hasattr(config, "neutral_framing")
    with pytest.raises(TypeError):
        HarnessConfig(neutral_framing=False)
    with pytest.raises(TypeError):
        HarnessConfig.from_flags(neutral_framing=False)


def test_safeevobench_exposes_only_the_neutral_bash_description():
    description = SAFEEVO_BASH_TOOL["description"]
    assert "operations workspace" in description
    assert "sandbox environment" not in description

    spec = make_spec(dataset_role="Operate the workspace.")
    assert spec.base_tools[0] is SAFEEVO_BASH_TOOL
