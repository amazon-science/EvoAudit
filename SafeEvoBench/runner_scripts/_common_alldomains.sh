#!/usr/bin/env bash
# Shared preamble for the ALL-DOMAINS "latest" memory+matrix experiment (one script per model).
#
# Each per-model runner sources THIS file, then calls `run_model <id> <short> <base_port>`.
# This preamble bakes in the experiment scope (all knobs stay overridable from the environment):
#   * DOMAINS   = devops fintech workplace           (all three)
#   * PAIR_SET  = latest   -> per base: prefer *r2, else *r1, else the original pair
#   * RUN_MATRIX=1 + RUN_INJECTED=1                   (matrix first, oracle arms afterwards)
#   * CONFIGS   = 4 primary mechanisms + their 3 meta counterparts, then base LAST (run_pairs.py cells):
#       memory skills subagents evolve        -> primary agent gets the mechanism's own tools
#       meta_memory meta_skills meta_evolve   -> harness-controlled counterparts (agent gets NO
#                                                corresponding tools). NB: there is no meta_subagents
#                                                in the harness, so `subagents` has no meta twin.
#       base                                  -> no mechanism (planning off) = the control floor for
#                                                "does the benchmark measure evolution impact?". Runs
#                                                LAST so the mechanism cells complete first.
#   * MEMORY_PROMPT_VARIANT = generalize   -> the voluntary-pull memory-consolidation variant, used by
#                                            BOTH the `memory` matrix cell and the oracle injected arms.
#   * REPLICATES=5, CONCURRENCY=6
#
# TWO-SERVER SPLIT (run the same model on two machines, each doing one half of the pairs):
#     server 1:   HALF=1 ./run_<model>.sh
#     server 2:   HALF=2 ./run_<model>.sh
# The pairs are split into SHARD_COUNT (default 2) contiguous halves, per domain, by sorted id.
# BOTH the matrix cells and the oracle arms honor the split (both go through select_pairs), so a
# given pair runs on exactly one machine. Both halves share RUN_TAG, so once both machines' results
# are copied into one CACHE_DIR they aggregate as one batch. To run everything on one machine, set
# SHARD_COUNT=1.

# --- experiment scope (override any of these from the environment) ---------------------------
export DOMAINS="${DOMAINS:-devops fintech workplace}"
export PAIR_SET="${PAIR_SET:-latest}"
export RUN_MATRIX="${RUN_MATRIX:-1}"
export RUN_INJECTED="${RUN_INJECTED:-1}"
export CONFIGS="${CONFIGS:-memory skills subagents evolve meta_memory meta_skills meta_evolve base}"
export MEMORY_PROMPT_VARIANT="${MEMORY_PROMPT_VARIANT:-generalize}"
# The generalize consolidation variant requires voluntary-pull memory. Pin MEMORY_MODE=pull (also
# run.py's default) so the `memory` matrix cell + oracle arms can't hard-error on a server whose
# environment happens to override it.
export MEMORY_MODE="${MEMORY_MODE:-pull}"
export REPLICATES="${REPLICATES:-5}"
export CONCURRENCY="${CONCURRENCY:-6}"
# Judge for BOTH the matrix (run_pairs --judge) and the oracle arms (run_memory_oracle --judge).
# Sonnet 4.6: proven on these dangerous tasks in prior runs. (Opus 5 was tried but its content
# filter trips on the data-destruction tasks -> stopReason=content_filtered -> unjudgeable.)
# Override with JUDGE_MODEL=...
export JUDGE_MODEL="${JUDGE_MODEL:-us.anthropic.claude-sonnet-4-6}"

# Shared cache + stable run-tag so the two halves (and all models) aggregate as one batch.
export CACHE_DIR="${CACHE_DIR:-.safeevo_cache/latest_alldomains}"
export RUN_TAG="${RUN_TAG:-latestall}"

# --- two-server split: HALF={1,2} selects this machine's half (SHARD_COUNT=2 by default) ------
export SHARD_COUNT="${SHARD_COUNT:-2}"
export SHARD_INDEX="${SHARD_INDEX:-${HALF:-1}}"

if [ "$SHARD_COUNT" -gt 1 ] && { [ "$SHARD_INDEX" -lt 1 ] || [ "$SHARD_INDEX" -gt "$SHARD_COUNT" ]; }; then
  echo "ERROR: HALF/SHARD_INDEX=$SHARD_INDEX must be in 1..$SHARD_COUNT (set HALF=1 or HALF=2)." >&2
  exit 1
fi
echo "latest all-domains run: shard $SHARD_INDEX/$SHARD_COUNT | domains=[$DOMAINS] | pairs=$PAIR_SET -> $CACHE_DIR (tag $RUN_TAG)"

source "$(dirname "${BASH_SOURCE[0]}")/_common_redesigned.sh"
