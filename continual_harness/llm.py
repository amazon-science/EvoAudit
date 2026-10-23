"""Thin LiteLLM wrapper for the Continual Harness: structured multi-turn tool calling.

Depends only on ``litellm``. This is the framework's single LLM client; benchmarks
use it as-is. ``OASLLMClient`` is kept as a back-compat alias for the old name.
"""

import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

import litellm

logger = logging.getLogger(__name__)

# Per-request wall-clock timeout (seconds). Without this, a single hung Bedrock connection
# blocks a run indefinitely (observed: a task wedged mid-chat, zero progress for minutes). A
# timeout turns that into a retryable error the loops below handle. Override via env.
REQUEST_TIMEOUT = float(os.environ.get("LLM_REQUEST_TIMEOUT", "180"))

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True
litellm.modify_params = True
# Drop provider-unsupported params instead of erroring. Some Bedrock models reject params we
# always send (e.g. qwen.qwen3-next-80b-a3b rejects `tool_choice`); dropping lets them run with
# tools rather than raising UnsupportedParamsError. litellm only drops genuinely-unsupported params.
litellm.drop_params = True
logging.getLogger("LiteLLM").setLevel(logging.ERROR)
logging.getLogger("litellm").setLevel(logging.ERROR)

TYPE_MAP = {
    "STRING": "string",
    "INTEGER": "integer",
    "BOOLEAN": "boolean",
    "ARRAY": "array",
    "OBJECT": "object",
    "NUMBER": "number",
}


def _convert_params(params: dict) -> dict:
    """Convert Gemini-style parameters to OpenAI JSON Schema format."""
    result = {}
    type_val = params.get("type_", params.get("type", "object"))
    result["type"] = TYPE_MAP.get(type_val, type_val.lower())

    if "description" in params:
        result["description"] = params["description"]

    if "properties" in params:
        result["properties"] = {}
        for prop_name, prop_def in params["properties"].items():
            result["properties"][prop_name] = _convert_params(prop_def)

    if "required" in params:
        result["required"] = params["required"]

    if "items" in params:
        result["items"] = _convert_params(params["items"])

    return result


def _is_timeout(e: Exception) -> bool:
    """True if the exception is a request timeout (litellm.Timeout or a timeout-shaped message)."""
    if e.__class__.__name__ in ("Timeout", "APITimeoutError"):
        return True
    s = str(e).lower()
    return "timeout" in s or "timed out" in s


def tools_to_openai_format(tools: List[dict]) -> List[dict]:
    """Convert Gemini-style tool declarations to OpenAI function-calling format."""
    openai_tools = []
    for tool in tools:
        params = tool.get("parameters", {})
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": _convert_params(params),
            },
        })
    return openai_tools


class LLMClient:
    """LiteLLM-based client for agent conversations with tool calling."""

    def __init__(self, model: str, system_prompt: str, tools: List[dict],
                 max_output_tokens: int = 4096):
        self.model = self._resolve_model(model)
        self.system_prompt = system_prompt
        self.tools = tools_to_openai_format(tools)
        self.max_output_tokens = max_output_tokens
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def chat(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Send structured messages, return parsed response.

        Args:
            messages: List of message dicts with role/content/tool_calls/tool_call_id

        Returns:
            {"text": str, "tool_calls": [{"id": str, "name": str, "args": dict}]}
        """
        full_messages = [{"role": "system", "content": self.system_prompt}] + messages

        for attempt in range(5):
            try:
                kwargs = dict(
                    model=self.model,
                    messages=full_messages,
                    tools=self.tools if self.tools else None,
                    tool_choice="auto" if self.tools else None,
                    max_tokens=self.max_output_tokens,
                    timeout=REQUEST_TIMEOUT,
                )
                # Some Bedrock reasoning models (GPT-5 family) reject `temperature` outright.
                if supports_temperature(self.model):
                    kwargs["temperature"] = 0.0
                response = litellm.completion(**kwargs)
                self._track_usage(response)
                return self._parse_response(response)

            except Exception as e:
                error_str = str(e)
                retryable = (
                    "ThrottlingException" in error_str or "TooManyRequests" in error_str
                    or "429" in error_str or _is_timeout(e)
                )
                if retryable:
                    wait = 2 ** attempt
                    logger.warning("Retryable LLM error (attempt %d), waiting %ds: %s",
                                   attempt + 1, wait, type(e).__name__)
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError("Failed after 5 retries")

    def _parse_response(self, response) -> Dict[str, Any]:
        """Extract text and tool calls from litellm response."""
        choice = response.choices[0]
        message = choice.message

        text = message.content or ""
        tool_calls = []

        if message.tool_calls:
            for tc in message.tool_calls:
                raw_args = tc.function.arguments
                parse_error = None
                if raw_args is None or raw_args == "":
                    args = {}
                    parse_error = "empty"
                elif isinstance(raw_args, dict):
                    args = raw_args
                else:
                    try:
                        args = json.loads(raw_args)
                        if not isinstance(args, dict):
                            args = {}
                            parse_error = "non-object"
                    except json.JSONDecodeError as e:
                        args = {}
                        parse_error = f"invalid JSON ({e}); raw={raw_args[:200]!r}"
                if parse_error:
                    logger.warning(
                        "Tool call '%s' had unparseable arguments (%s)",
                        tc.function.name, parse_error,
                    )
                tool_calls.append({
                    "id": tc.id or str(uuid.uuid4()),
                    "name": tc.function.name,
                    "args": args,
                    "arg_parse_error": parse_error,
                })

        return {"text": text, "tool_calls": tool_calls}

    def _track_usage(self, response):
        """Track cumulative token usage."""
        usage = getattr(response, "usage", None)
        if usage:
            self.total_input_tokens += getattr(usage, "prompt_tokens", 0)
            self.total_output_tokens += getattr(usage, "completion_tokens", 0)

    @staticmethod
    def _resolve_model(model: str) -> str:
        """Auto-prefix model names for litellm routing."""
        return resolve_model(model)


# Back-compat alias for the former class name.
OASLLMClient = LLMClient


# Bedrock-hosted OpenAI GPT-5 reasoning models (e.g. "openai.gpt-5.6-luna") need special handling
# that resolve_model + the call sites apply automatically:
#   1. Route via the Converse API. The default Invoke route returns OpenAI-native chat JSON that
#      litellm cannot parse ("BedrockException - Error processing=...").
#   2. Register them as function-calling capable. litellm's model map doesn't know these ids, so with
#      drop_params=True it silently strips the `tools` param — leaving the agent with no tools (the
#      model then answers "I don't have access to that tool"). register_model stops the stripping.
#   3. Omit the `temperature` param, which these models reject ("Unsupported parameter: 'temperature'").
# gpt-oss (openai.gpt-oss-*) is NOT one of these — it works on the default Invoke route with tools and
# accepts temperature — so the "openai.gpt-5" match below is deliberately narrow.
_registered_fc_models: set = set()


def _is_bedrock_gpt5(model: str) -> bool:
    """True for Bedrock-hosted OpenAI GPT-5 family ids (routed or bare)."""
    return "openai.gpt-5" in model


def _register_fc_support(model: str) -> None:
    """Declare a Bedrock model function-calling capable so drop_params won't strip `tools`.

    litellm looks up function-calling support under the UNROUTED id (and sometimes the
    region-stripped id), not the ``bedrock/converse/`` route string — so register every variant.
    """
    if model in _registered_fc_models:
        return
    keys = {model}
    for rp in ("us.", "eu.", "apac.", "us-gov."):
        if model.startswith(rp):
            keys.add(model[len(rp):])
    keys |= {f"bedrock/converse/{k}" for k in list(keys)} | {f"bedrock/{k}" for k in list(keys)}
    for k in keys:
        try:
            litellm.register_model({k: {
                "litellm_provider": "bedrock_converse",
                "supports_function_calling": True,
                "mode": "chat",
            }})
        except Exception:  # registration is best-effort; never block a call on it
            pass
    _registered_fc_models.add(model)


def supports_temperature(model: str) -> bool:
    """False for models that reject the `temperature` param (Bedrock GPT-5 reasoning models)."""
    return not _is_bedrock_gpt5(model)


def resolve_model(model: str) -> str:
    """Auto-prefix model names for litellm routing.

    Bedrock model ids look like ``<provider>.<model>-v1:0`` (e.g.
    ``us.anthropic.claude-...``, ``qwen.qwen3-32b-v1:0``, ``meta.llama3-...``)
    or carry a region/cross-region prefix (``us.``/``eu.``/``apac.``). Prefix
    all of these with ``bedrock/`` so litellm routes them to Bedrock reliably
    (both for completion and get_model_info), rather than relying on litellm's
    fuzzy provider inference which varies across versions.

    Bedrock GPT-5 reasoning ids (``openai.gpt-5*``) are routed via ``bedrock/converse/`` and
    registered as tool-capable (see the note above ``_is_bedrock_gpt5``).
    """
    if "/" in model:
        return model
    # Provider/anthropic-style short names for non-Bedrock SDKs.
    if model.startswith("claude-"):
        return f"anthropic/{model}"
    if model.startswith("gpt-") or model.startswith("o3") or model.startswith("o4"):
        return f"openai/{model}"
    # Bedrock ids: a "<vendor>.<model>" token (optionally region-prefixed) or a
    # trailing version tag like "-v1:0". Covers anthropic, meta, qwen, mistral,
    # amazon (nova/titan), cohere, ai21, deepseek, etc.
    _BEDROCK_VENDORS = (
        "anthropic.", "meta.", "qwen.", "mistral.", "amazon.", "cohere.",
        "ai21.", "deepseek.", "stability.", "writer.", "openai.", "zai.",
    )
    _BEDROCK_REGION_PREFIXES = ("us.", "eu.", "apac.", "us-gov.")
    stripped = model
    for rp in _BEDROCK_REGION_PREFIXES:
        if model.startswith(rp):
            stripped = model[len(rp):]
            break
    if stripped.startswith(_BEDROCK_VENDORS) or model.startswith(_BEDROCK_VENDORS):
        if _is_bedrock_gpt5(model):
            _register_fc_support(model)
            return f"bedrock/converse/{model}"
        return f"bedrock/{model}"
    return model


def text_completion(prompt: str, model: str, module_name: str = "TextCompletion") -> str:
    """Simple text-in/text-out LLM call via litellm. No tools, no multi-turn.

    Args:
        prompt: The full prompt text
        model: Model name (auto-prefixed if needed)
        module_name: Label for logging

    Returns:
        Response text as a string
    """
    resolved = resolve_model(model)

    for attempt in range(5):
        try:
            kwargs = dict(
                model=resolved,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                timeout=REQUEST_TIMEOUT,
            )
            # GPT-5-family Bedrock models reject `temperature`; omit it for them.
            if supports_temperature(resolved):
                kwargs["temperature"] = 0.0
            response = litellm.completion(**kwargs)
            text = response.choices[0].message.content or ""
            logger.debug("[%s] %d tokens in, %d tokens out", module_name,
                        getattr(response.usage, "prompt_tokens", 0),
                        getattr(response.usage, "completion_tokens", 0))
            return text

        except Exception as e:
            error_str = str(e)
            if ("ThrottlingException" in error_str or "TooManyRequests" in error_str
                    or "429" in error_str or _is_timeout(e)):
                wait = 2 ** attempt
                logger.warning("[%s] Retryable LLM error (attempt %d), waiting %ds: %s",
                               module_name, attempt + 1, wait, type(e).__name__)
                time.sleep(wait)
            else:
                raise

    raise RuntimeError(f"[{module_name}] Failed after 5 retries")
