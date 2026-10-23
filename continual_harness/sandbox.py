"""Sandbox execution backends for the Continual Harness.

A sandbox is anything with ``execute(command, timeout) -> {stdout, stderr,
returncode}``. The framework ships:
  - ``BaseSandbox``: the abstract interface,
  - ``MockSandbox``: canned responses for tests / no-Docker development.

Benchmarks provide their own concrete backend (e.g. an HTTP-backed Docker
sandbox) following the same interface.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class BaseSandbox(ABC):
    """Abstract base for sandbox execution backends."""

    @abstractmethod
    def execute(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        """Execute a bash command and return {stdout, stderr, returncode}."""
        raise NotImplementedError

    def reset(self, scenario_path: str) -> None:  # optional
        pass

    def reset_workspace(self) -> None:  # optional
        """Return the workspace to its pristine initial state (no-op by default).

        Concrete backends whose workspace is a recreatable artifact (e.g. a baked
        Docker image) override this to give the store-only pair arm a clean
        between-task reset while host-side evolution stores persist. Backends without
        a resettable workspace safely inherit the no-op."""
        pass

    def teardown(self) -> None:  # optional
        pass


class MockSandbox(BaseSandbox):
    """Mock sandbox for development/testing without Docker.

    Returns a canned response and records the command history. Useful for
    exercising the agent loop and LLM integration without a real sandbox.
    """

    def __init__(self, default_response: Optional[Dict[str, Any]] = None):
        self.default_response = default_response or {
            "stdout": "[MockSandbox] Command executed successfully.",
            "stderr": "",
            "returncode": 0,
        }
        self.history: list = []

    def execute(self, command: str, timeout: int = 60) -> Dict[str, Any]:
        self.history.append(command)
        logger.debug("MockSandbox execute: %s", command)
        return dict(self.default_response)

    def reset(self, scenario_path: str) -> None:
        self.history = []
        logger.info("MockSandbox reset for scenario: %s", scenario_path)

    def teardown(self) -> None:
        pass
