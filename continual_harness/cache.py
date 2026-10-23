"""Run-scoped cache paths for the Continual Harness.

The stores, evolver, and trajectory logging all persist under a per-run cache
directory ``{AGENT_CACHE_BASE}/{run_id}/``. This module owns the resolution of
that directory with no dependency on any benchmark or on the legacy
``run_data_manager`` (which previously hosted ``get_cache_path``).

Resolution order for the run id:
  1. an id set explicitly via :func:`set_run_id` (what the agent calls on init),
  2. the ``RUN_DATA_ID`` environment variable,
  3. none — fall back to the bare ``{AGENT_CACHE_BASE}/`` directory.

The cache base defaults to ``.continual_cache`` and is overridable via the
``AGENT_CACHE_BASE`` environment variable (e.g. ``.essr_cache``).
"""

import os
from pathlib import Path
from typing import Optional

_DEFAULT_CACHE_BASE = ".continual_cache"

# Process-global current run id. Set once per run by the agent.
_run_id: Optional[str] = None


def set_run_id(run_id: Optional[str]) -> None:
    """Set the active run id used to scope the cache directory."""
    global _run_id
    _run_id = run_id


def get_run_id() -> Optional[str]:
    """Return the active run id (explicit set wins over ``RUN_DATA_ID`` env)."""
    return _run_id or os.environ.get("RUN_DATA_ID")


def get_cache_base() -> Path:
    """Return the cache base dir (``AGENT_CACHE_BASE`` env or the default)."""
    return Path(os.environ.get("AGENT_CACHE_BASE", _DEFAULT_CACHE_BASE))


def get_cache_directory() -> Path:
    """Return ``{base}/{run_id}/`` (created), or ``{base}/`` if no run id."""
    base = get_cache_base()
    run_id = get_run_id()
    cache_dir = base / run_id if run_id else base
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_cache_path(relative_path: str) -> Path:
    """Return a path within the run-scoped cache directory."""
    return get_cache_directory() / relative_path
