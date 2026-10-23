#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Kimi K2.5. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_kimi.sh   |   server 2: HALF=2 ./run_latest_kimi.sh
# Verified working (tool-calling). See _common_alldomains.sh for scope.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "moonshotai.kimi-k2.5" "kimi-k2.5" "${BASE_PORT:-8200}"
