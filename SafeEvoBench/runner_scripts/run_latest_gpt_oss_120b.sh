#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for GPT-OSS-120B. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_gpt_oss_120b.sh   |   server 2: HALF=2 ./run_latest_gpt_oss_120b.sh
# Verified working Bedrock id (invocable on-demand as given). See _common_alldomains.sh for scope.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "openai.gpt-oss-120b-1:0" "gpt-oss-120b" "${BASE_PORT:-9400}"
