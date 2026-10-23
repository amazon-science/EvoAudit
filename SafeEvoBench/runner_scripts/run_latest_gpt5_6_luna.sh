#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for GPT-5.6 "luna". Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_gpt5_6_luna.sh   |   server 2: HALF=2 ./run_latest_gpt5_6_luna.sh
#
# GPT-5-on-Bedrock needs special handling, applied automatically in continual_harness/llm.py
# resolve_model(): the "openai.gpt-5*" id is routed via the Converse API, registered as
# function-calling capable (else litellm's drop_params strips `tools` and the agent gets none), and
# the `temperature` param is omitted (this model rejects it). Verified end-to-end: emits tool_calls
# and handles multi-turn tool results. No litellm upgrade required (works on 1.89.3).
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "us.openai.gpt-5.6-luna" "gpt5.6-luna" "${BASE_PORT:-10800}"
