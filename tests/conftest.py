"""Test-only fallbacks for optional runtime dependencies."""

import sys
from types import ModuleType


try:
    import litellm  # noqa: F401
except ModuleNotFoundError:
    litellm_stub = ModuleType("litellm")

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("litellm is unavailable in this test environment")

    litellm_stub.completion = unavailable
    litellm_stub.get_model_info = unavailable
    litellm_stub.token_counter = unavailable
    litellm_stub.suppress_debug_info = True
    litellm_stub.modify_params = True
    litellm_stub.drop_params = True
    sys.modules["litellm"] = litellm_stub
