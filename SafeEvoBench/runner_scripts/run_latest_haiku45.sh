#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Haiku 4.5. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_haiku45.sh   |   server 2: HALF=2 ./run_latest_haiku45.sh
# Verified working Bedrock id (us. inference profile). See _common_alldomains.sh for scope.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "us.anthropic.claude-haiku-4-5-20251001-v1:0" "haiku45" "${BASE_PORT:-7000}"
