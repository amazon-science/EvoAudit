#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for Llama 3.3 70B Instruct. Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_llama3_3_70b.sh   |   server 2: HALF=2 ./run_latest_llama3_3_70b.sh
# NOTE: the bare "meta.llama3-3-70b-instruct-v1:0" is not on-demand invocable; use the us. profile.
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "us.meta.llama3-3-70b-instruct-v1:0" "llama3-3-70b" "${BASE_PORT:-10000}"
