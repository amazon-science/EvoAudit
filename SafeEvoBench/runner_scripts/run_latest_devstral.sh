#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Devstral 2 123B. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_devstral.sh   |   server 2: HALF=2 ./run_latest_devstral.sh
# Verified working Bedrock id (invocable on-demand as given). See _common_alldomains.sh for scope.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "mistral.devstral-2-123b" "devstral" "${BASE_PORT:-10400}"
