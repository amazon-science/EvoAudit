#!/usr/bin/env bash
# Shared runner for the REDESIGNED-pair experiment
# (devops 51-62 bands + all fintech + all workplace).
#
# One model wrapper covers both runners and every requested condition:
#   - run_pairs.py     : the evolution matrix conditions {memory, meta_memory, skills}
#                        (cold vs evolved; the primary agent gets the mechanism's tools)
#   - run_memory_oracle.py : the injected-memory arms per pair
#                        (cold + agent_memory + oracle_{good_safety,bad_safety,good_utility,bad_utility})
#
# Scope decisions baked in (per experiment spec):
#   * Pairs      : redesigned devops (BB/BD/DB/DD 51-62), all fintech, and all workplace.
#   * Configs    : memory, meta_memory, skills  (run_pairs.py)   +   injected arms (oracle, memory-adjacent).
#   * Injected   : run once per pair via the oracle runner (it seeds a memory store, so it belongs
#                  with the memory mechanism); NOT re-run under meta_memory/skills.
#   * Replicates : 5 (override with REPLICATES=).
#
# AWS auth is caller-controlled: no profile or region is forced here (a host that authenticates
# via an instance role has no named profile). Only AWS_PROFILE / AWS_REGION already set by the
# caller are exported.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

PY="${PY:-python}"
PAIRS_RUNNER="${PAIRS_RUNNER:-$REPO/benchmarks/safeevobench/run_pairs.py}"
ORACLE_RUNNER="${ORACLE_RUNNER:-$REPO/SafeEvoBench/runner_scripts/run_memory_oracle.py}"

[ -n "${AWS_PROFILE:-}" ] && export AWS_PROFILE
[ -n "${AWS_REGION:-}" ]  && export AWS_REGION

# --- knobs (all overridable from the environment) ---------------------------------------------
REPLICATES="${REPLICATES:-5}"
CONCURRENCY="${CONCURRENCY:-6}"          # per run_pairs cell / per oracle run; keep <= (cores-2)
CONFIGS="${CONFIGS:-memory meta_memory skills}"   # run_pairs.py evolution conditions
EVOLUTION_PROMPT_VARIANT="${EVOLUTION_PROMPT_VARIANT:-current}"
# Memory-consolidation prompt variant forwarded to the oracle runner's injected arms
# (current|generalize|generalize_urgent|generalize_urgent_trust). Non-current values require
# MEMORY_MODE=pull, which is the default in run.py. Left at "current" the oracle command is
# unchanged (byte-identical to prior batches).
MEMORY_PROMPT_VARIANT="${MEMORY_PROMPT_VARIANT:-current}"
DOMAINS="${DOMAINS:-devops fintech}"
RUN_INJECTED="${RUN_INJECTED:-1}"        # 1 = also run the oracle injected-memory arms
RUN_MATRIX="${RUN_MATRIX:-1}"            # 1 = also run the run_pairs.py evolution matrix
# INVERT=1 runs each SELECTED pair in reverse (source<->target) via run_pairs --invert-pairs. It
# composes with PAIR_SET (inversion happens after selection, inside run_pairs). The hand-authored
# oracle injected memories are forward-only, so INVERT forces the injected arms OFF.
INVERT="${INVERT:-0}"
if [ "$INVERT" = "1" ] && [ "$RUN_INJECTED" = "1" ]; then
  echo "INVERT=1: oracle injected memories are forward-only -> forcing RUN_INJECTED=0 (matrix only)." >&2
  RUN_INJECTED="0"
fi
CACHE_DIR="${CACHE_DIR:-.safeevo_cache/redesigned_experiments}"
ORACLE_CACHE_DIR="${ORACLE_CACHE_DIR:-$CACHE_DIR/oracle}"
DRY_RUN="${DRY_RUN:-0}"
RUN_TAG="${RUN_TAG:-$(date -u +%Y%m%d_%H%M%S)}"
JUDGE_MODEL="${JUDGE_MODEL:-us.anthropic.claude-sonnet-4-6}"
# Which pair set to run:
#   redesigned = the original null-experiment bands (devops 51-62, fintech/workplace 01-N).
#   refactored = ONLY the refactored *r1 pairs authored this pass (discovered from pairs.json).
#   combined   = the full band with each refactored base swapped for its *r1 version
#                (refactored pairs + the originals left unchanged) -> one row per original pair.
#   latest     = the full band with each base resolved to its NEWEST variant: prefer *r2, else *r1,
#                else the original pair -> one row per base.
PAIR_SET="${PAIR_SET:-redesigned}"
# Restrict to a subset of pairs (comma-separated, domain-qualified). Empty = the whole selected set.
ONLY_PAIRS="${ONLY_PAIRS:-}"
# Sharding: split the SELECTED pairs across machines; this machine runs shard SHARD_INDEX (1-based) of
# SHARD_COUNT. Default SHARD_COUNT=1 => no split (backward compatible). Contiguous split by sorted id.
SHARD_INDEX="${SHARD_INDEX:-1}"
SHARD_COUNT="${SHARD_COUNT:-1}"

DEVOPS_GROUP="SafeEvoBench/devops"
FINTECH_GROUP="SafeEvoBench/fintech"
WORKPLACE_GROUP="SafeEvoBench/workplace"
DEVOPS_IMAGE="${DEVOPS_IMAGE:-safeevo-devops-v2:latest}"
FINTECH_IMAGE="${FINTECH_IMAGE:-safeevo-fintech-v2:latest}"
WORKPLACE_IMAGE="${WORKPLACE_IMAGE:-safeevo-workplace-v2:latest}"

# --- redesigned pair id sets (the ONLY pairs this experiment touches) -------------------------
# devops: the 12-per-quadrant band (01-12).
# fintech: all 40 (01-10 per quadrant).
# workplace: all 54 (13 BB, 14 BD, 13 DB, 14 DD).
devops_pairs() {
  local q p out=()
  for q in BB BD DB DD; do for p in $(seq -w 1 12); do out+=("devops_${q}${p}"); done; done
  ( IFS=,; printf '%s' "${out[*]}" )
}
fintech_pairs() {
  local q p out=()
  for q in BB BD DB DD; do for p in $(seq -w 1 10); do out+=("fintech_${q}${p}"); done; done
  ( IFS=,; printf '%s' "${out[*]}" )
}
workplace_pairs() {
  local q p limit out=()
  for q in BB BD DB DD; do
    case "$q" in BB|DB) limit=13;; BD|DD) limit=14;; esac
    for p in $(seq -w 1 "$limit"); do out+=("workplace_${q}${p}"); done
  done
  ( IFS=,; printf '%s' "${out[*]}" )
}
# Refactored set: every *r1 pair present in the domain's pairs.json (comma-separated).
refactored_pairs() {
  "$PY" -c "import json;print(','.join(sorted(p['id'] for p in json.load(open('SafeEvoBench/$1/pairs.json'))['pairs'] if p['id'].endswith('r1'))))"
}
# r2 set: every *r2 pair present in the domain's pairs.json (the de-saturation refactor pass).
r2_pairs() {
  "$PY" -c "import json;print(','.join(sorted(p['id'] for p in json.load(open('SafeEvoBench/$1/pairs.json'))['pairs'] if p['id'].endswith('r2'))))"
}
# Combined set: the full redesigned band with each refactored base swapped for its *r1 version
# (i.e. refactored pairs + the originals left unchanged). One row per original pair.
combined_pairs() {
  "$PY" - "$1" <<'PYEOF'
import json,sys
dom=sys.argv[1]
have={p["id"] for p in json.load(open(f"SafeEvoBench/{dom}/pairs.json"))["pairs"]}
r1=sorted(p for p in have if p.endswith("r1"))
bases={p[:-2] for p in r1}                     # 'devops_BD53r1' -> 'devops_BD53'
if dom=="devops":
    band=[f"devops_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,13)]
elif dom=="fintech":
    band=[f"fintech_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,11)]
else:
    lim={"BB":13,"BD":14,"DB":13,"DD":14}
    band=[f"workplace_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,lim[q]+1)]
out=[b for b in band if b not in bases]+r1      # unchanged originals + refactored versions
print(",".join(out))
PYEOF
}
# Latest set: the full redesigned band with each base resolved to its NEWEST available variant --
# prefer *r2, else *r1, else the original (unrefactored) pair. One row per base. A base with no
# variant present in pairs.json at all is skipped.
latest_pairs() {
  "$PY" - "$1" <<'PYEOF'
import json,sys
dom=sys.argv[1]
have={p["id"] for p in json.load(open(f"SafeEvoBench/{dom}/pairs.json"))["pairs"]}
if dom=="devops":
    band=[f"devops_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,13)]
elif dom=="fintech":
    band=[f"fintech_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,11)]
else:
    lim={"BB":13,"BD":14,"DB":13,"DD":14}
    band=[f"workplace_{q}{n:02d}" for q in ("BB","BD","DB","DD") for n in range(1,lim[q]+1)]
out=[]
for base in band:
    if   base+"r2" in have: out.append(base+"r2")   # prefer the de-saturation refactor
    elif base+"r1" in have: out.append(base+"r1")   # else the first refactor
    elif base      in have: out.append(base)        # else the original, unrefactored pair
    # else: no variant present -> nothing to run for this base
print(",".join(out))
PYEOF
}

group_for_domain() {
  case "$1" in
    devops) printf '%s' "$DEVOPS_GROUP";;
    fintech) printf '%s' "$FINTECH_GROUP";;
    workplace) printf '%s' "$WORKPLACE_GROUP";;
  esac
}

image_for_domain() {
  case "$1" in
    devops) printf '%s' "$DEVOPS_IMAGE";;
    fintech) printf '%s' "$FINTECH_IMAGE";;
    workplace) printf '%s' "$WORKPLACE_IMAGE";;
  esac
}

# Split a comma-separated pair list into SHARD_COUNT contiguous shards (by sorted id) and emit shard
# SHARD_INDEX (1-based). SHARD_COUNT<=1 passes the list through unchanged (default; backward compatible).
shard_filter() {
  if [ "${SHARD_COUNT:-1}" -le 1 ]; then cat; return 0; fi
  local input; input="$(cat)"   # the piped comma list (stdin is the heredoc SCRIPT below, so pass via env)
  SHARD_LIST="$input" SHARD_INDEX="${SHARD_INDEX:-1}" SHARD_COUNT="$SHARD_COUNT" "$PY" - <<'PYEOF'
import os,math
ids=[x for x in os.environ.get("SHARD_LIST","").split(",") if x]
ids.sort()
n=max(1,int(os.environ["SHARD_COUNT"])); idx=int(os.environ["SHARD_INDEX"])
size=math.ceil(len(ids)/n) if ids else 0
start=(idx-1)*size
print(",".join(ids[start:start+size]))
PYEOF
}

# Intersect a domain's full selected set with ONLY_PAIRS (if the caller narrowed scope), then apply the
# SHARD split (if SHARD_COUNT>1) so this machine runs only its shard.
select_pairs() {
  local domain="$1" full sel
  if [ "$PAIR_SET" = "refactored" ]; then
    full="$(refactored_pairs "$domain")"
  elif [ "$PAIR_SET" = "r2" ]; then
    full="$(r2_pairs "$domain")"
  elif [ "$PAIR_SET" = "latest" ]; then
    full="$(latest_pairs "$domain")"
  elif [ "$PAIR_SET" = "combined" ]; then
    full="$(combined_pairs "$domain")"
  else
    case "$domain" in
      devops)  full="$(devops_pairs)";;
      fintech) full="$(fintech_pairs)";;
      workplace) full="$(workplace_pairs)";;
    esac
  fi
  if [ -z "$ONLY_PAIRS" ]; then
    sel="$full"
  else
    local keep=() id w
    IFS=',' read -ra want <<< "$ONLY_PAIRS"
    for id in $(echo "$full" | tr ',' ' '); do
      for w in "${want[@]}"; do [ "$id" = "$w" ] && keep+=("$id"); done
    done
    if [ "${#keep[@]}" -eq 0 ]; then sel=""; else sel="$(IFS=,; printf '%s' "${keep[*]}")"; fi
  fi
  printf '%s' "$sel" | shard_filter
}

preflight() {
  [ "${SKIP_PREFLIGHT:-0}" = "1" ] && return 0
  echo "--- preflight (PAIR_SET=$PAIR_SET) ---"
  # 1) every SELECTED pair loads from pairs.json + has its 4 injected arms in oracle_memories.json.
  local dom pairs
  for dom in $DOMAINS; do
    pairs="$(select_pairs "$dom")"
    if [ -z "$pairs" ]; then echo "  $dom: no selected pairs, skip"; continue; fi
    DOM="$dom" SEL="$pairs" "$PY" - <<'PYEOF'
import json,os,sys
dom=os.environ["DOM"]; sel=os.environ["SEL"].split(",")
pairs={p["id"] for p in json.load(open(f"SafeEvoBench/{dom}/pairs.json"))["pairs"]}
om=json.load(open(f"SafeEvoBench/{dom}/oracle_memories.json"))["memories"]
ok=True
for pid in sel:
    if pid not in pairs: print(f"  MISSING pair in pairs.json: {pid}"); ok=False; continue
    e=om.get(pid)
    if not e: print(f"  MISSING oracle_memories entry: {pid}"); ok=False; continue
    keys={k for k in e if k.endswith("_memory")}
    want={"good_safety_memory","bad_safety_memory","good_utility_memory","bad_utility_memory"}
    if not want.issubset(keys):
        print(f"  {pid}: injected arms incomplete -> {sorted(keys)}"); ok=False
print(f"  {dom}: {len(sel)} pairs selected, injected arms present" if ok else f"  {dom}: VALIDATION FAILED")
sys.exit(0 if ok else 1)
PYEOF
  done
  if [ "$DRY_RUN" = "1" ]; then echo "  dry run: skipped Docker digest + Bedrock checks"; return 0; fi
  # 2) image digest matches tasks.json (guards against a stale image).
  local dom img want got docker_output
  for dom in $DOMAINS; do
    img="$(image_for_domain "$dom")"
    want="$("$PY" -c "import json;print(json.load(open('SafeEvoBench/$dom/tasks.json'))['build_digest'])")"
    if ! docker_output="$(docker run --rm "$img" cat /etc/img_build.digest 2>&1)"; then
      echo "PREFLIGHT FAILED: required image '$img' for $dom is unavailable or could not start." >&2
      echo "  Docker error: $docker_output" >&2
      echo "  Build it with: docker build -t $img SafeEvoBench/$dom/" >&2
      exit 1
    fi
    got="$(printf '%s' "$docker_output" | tr -d '[:space:]')"
    if [ "$want" != "$got" ]; then
      echo "PREFLIGHT FAILED: $img digest '$got' != tasks.json '$want'." >&2
      echo "  Rebuild: docker build -t $img SafeEvoBench/$dom/" >&2
      exit 1
    fi
    echo "  $dom: image digest OK ($got)"
  done
}

print_cmd() { printf '  '; printf '%q ' "$@"; printf '\n'; }

# $1 model id, $2 short label, $3 base port
run_model() {
  local model="$1" short="$2" base_port="$3"
  echo "======================================================================"
  echo " model=$short ($model)  RUN_TAG=$RUN_TAG  reps=$REPLICATES"
  echo "   matrix configs: ${RUN_MATRIX:+$CONFIGS}${RUN_MATRIX:+ }| evolution variant: $EVOLUTION_PROMPT_VARIANT | injected arms: $([ "$RUN_INJECTED" = 1 ] && echo "yes (memory variant: $MEMORY_PROMPT_VARIANT)" || echo no)"
  echo "======================================================================"
  preflight

  # Runs execute SERIALLY inside this wrapper (each blocks to completion), so a run's ports free
  # before the next starts. We rotate within a bounded per-model window [base_port, base_port+span)
  # rather than reuse one port (avoids a TIME_WAIT collision when the next run reclaims it too
  # fast). The 4 model wrappers use disjoint base_ports so two models launched in parallel never
  # collide. `slot` is a plain shell var incremented in the main shell (NOT a subshell, or the
  # increment would be lost); `port` is recomputed from it before each run below.
  local span="${PORT_SPAN:-400}"
  local step=$(( CONCURRENCY + 2 ))
  local nslots=$(( span / step )); [ "$nslots" -lt 1 ] && nslots=1
  local slot=0 port

  # ---- A) evolution matrix conditions (run_pairs.py) -------------------------------------------
  if [ "$RUN_MATRIX" = "1" ]; then
    local domain group image pairs config port
    for domain in $DOMAINS; do
      group="$(group_for_domain "$domain")"
      image="$(image_for_domain "$domain")"
      pairs="$(select_pairs "$domain")"
      [ -z "$pairs" ] && { echo ">>> $short/$domain: no selected pairs, skip"; continue; }
      for config in $CONFIGS; do
        port=$(( base_port + (slot % nslots) * step )); slot=$(( slot + 1 ))
        local cmd=(
          "$PY" "$PAIRS_RUNNER"
          --group "$REPO/$group"
          --docker-image "$image"
          --model "$model" --model-short "$short"
          --judge "$JUDGE_MODEL"
          --config "$config"
          --pairs "$pairs"
          --replicates "$REPLICATES"
          --concurrency "$CONCURRENCY"
          --cache-dir "$CACHE_DIR"
          --port "$port"
          --timestamp "$RUN_TAG"
          --evolution-prompt-variant "$EVOLUTION_PROMPT_VARIANT"
          --resume
        )
        # Forward a non-current memory-consolidation variant (e.g. generalize) to the matrix, but
        # ONLY for voluntary-memory configs (those with --enable-memory). run_pairs.py hard-errors
        # if it's given a non-memory config, so meta_memory/skills/subagents/evolve/base are excluded.
        if [ "$MEMORY_PROMPT_VARIANT" != "current" ]; then
          case "$config" in
            memory|memory+evolve|all) cmd+=( --memory-prompt-variant "$MEMORY_PROMPT_VARIANT" );;
          esac
        fi
        # Reverse each selected pair (source<->target). Composes with PAIR_SET (inversion is applied
        # inside run_pairs, after --pairs selection).
        [ "$INVERT" = "1" ] && cmd+=( --invert-pairs )
        echo ">>> matrix  $short / $domain / $config$([ "$INVERT" = "1" ] && echo " (inverted)")  (port $port)"
        if [ "$DRY_RUN" = "1" ]; then print_cmd "${cmd[@]}"; else "${cmd[@]}"; fi
      done
    done
  fi

  # ---- B) injected-memory arms (run_memory_oracle.py), one run per pair ------------------------
  # Each oracle run yields: cold + agent_memory + oracle_{good_safety,bad_safety,good_utility,bad_utility}.
  if [ "$RUN_INJECTED" = "1" ]; then
    local domain group image pairs pid port
    for domain in $DOMAINS; do
      group="$(group_for_domain "$domain")"
      image="$(image_for_domain "$domain")"
      pairs="$(select_pairs "$domain")"
      [ -z "$pairs" ] && continue
      for pid in $(echo "$pairs" | tr ',' ' '); do
        port=$(( base_port + (slot % nslots) * step )); slot=$(( slot + 1 ))
        local cmd=(
          "$PY" "$ORACLE_RUNNER"
          --group "$REPO/$group"
          --pair "$pid"
          --model "$model" --model-short "$short"
          --judge "$JUDGE_MODEL"
          --docker-image "$image"
          --replicates "$REPLICATES"
          --concurrency "$CONCURRENCY"
          --run-tag "$RUN_TAG"
          --port "$port"
          --cache-dir "$ORACLE_CACHE_DIR"
        )
        # Forward a non-default memory-prompt variant (e.g. generalize) to the oracle runner.
        [ "$MEMORY_PROMPT_VARIANT" != "current" ] && cmd+=( --memory-prompt-variant "$MEMORY_PROMPT_VARIANT" )
        echo ">>> inject  $short / $pid  (port $port)"
        if [ "$DRY_RUN" = "1" ]; then print_cmd "${cmd[@]}"; else "${cmd[@]}"; fi
      done
    done
  fi

  echo "DONE model=$short RUN_TAG=$RUN_TAG"
  [ "$DRY_RUN" = "1" ] && echo "(dry run: no model calls or containers launched)"
}
