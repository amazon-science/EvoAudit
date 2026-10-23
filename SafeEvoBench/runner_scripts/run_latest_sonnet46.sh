#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Sonnet 4.6. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_sonnet46.sh   |   server 2: HALF=2 ./run_latest_sonnet46.sh
# Verified working Bedrock id (needs the us. inference profile). See _common_alldomains.sh for scope.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "us.anthropic.claude-sonnet-4-6" "sonnet46" "${BASE_PORT:-7600}"
