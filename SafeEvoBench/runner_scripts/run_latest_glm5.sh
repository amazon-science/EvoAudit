#!/usr/bin/env bash
# ALL-DOMAINS "latest" memory+matrix run for GLM-5 (Z.ai). Two-server split via HALF={1,2}.
#   server 1: HALF=1 ./run_latest_glm5.sh   |   server 2: HALF=2 ./run_latest_glm5.sh
# Verified working. NB: the "zai." vendor prefix was added to resolve_model() so this routes to
# bedrock/zai.glm-5 deterministically (rather than relying on litellm's fuzzy provider inference).
source "$(dirname "${BASH_SOURCE[0]}")/_common_alldomains.sh"
run_model "zai.glm-5" "glm-5" "${BASE_PORT:-11600}"
