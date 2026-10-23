#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Qwen3-Next-80B-A3B. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_qwen_next80b.sh   |   server 2: HALF=2 ./run_latest_qwen_next80b.sh
# NOTE: correct Bedrock id ends in "-a3b" (the bare "-a3" you supplied is rejected as invalid).
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "qwen.qwen3-next-80b-a3b" "qwen-next80b" "${BASE_PORT:-8800}"
