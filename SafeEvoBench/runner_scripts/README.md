# Experiment runners

The `run_latest_*.sh` wrappers run the all-domains "latest" memory + evolution-matrix experiment —
one wrapper per model. Each sources `_common_alldomains.sh`, which bakes in the experiment scope
(all knobs stay overridable from the environment):

- **Domains:** `devops fintech workplace`
- **Pair set:** `latest` — per base, prefer the newest variant present in `pairs.json` (`*r2`, else
  `*r1`, else the bare pair). Selection lives in `_common_redesigned.sh` (`latest_pairs`).
- **Arms:** the evolution matrix (`run_pairs.py`) **and** the injected-memory oracle arms
  (`run_memory_oracle.py`), run per pair.
- **Matrix configs:** `memory skills subagents evolve meta_memory meta_skills meta_evolve base`
- **Judge:** `us.anthropic.claude-sonnet-4-6` · **Replicates:** 5 · **Concurrency:** 6

## Files

| File | Role |
|---|---|
| `run_latest_<model>.sh` | Per-model entry point; sources `_common_alldomains.sh` and calls `run_model`. |
| `_common_alldomains.sh` | Experiment scope + two-server split; sources `_common_redesigned.sh`. |
| `_common_redesigned.sh` | Pair selection (`latest_pairs`) and the `run_model` driver. |
| `run_memory_oracle.py` | The oracle injected-memory runner (reads each domain's `oracle_memories.json`). |

The evolution-matrix runner itself is `benchmarks/safeevobench/run_pairs.py` (outside this directory).

## Run

```bash
cd <repo root>
./SafeEvoBench/runner_scripts/run_latest_haiku45.sh
```

Available models: `haiku45`, `sonnet46`, `kimi`, `qwen_next80b`, `gpt_oss_120b`, `glm5`,
`devstral`, `llama3_3_70b`, `gpt5_6_luna`.

### Two-server split

Split the pairs across two machines with `HALF={1,2}` (contiguous halves per domain, by sorted id;
both halves share `RUN_TAG` so results aggregate as one batch):

```bash
# server 1
HALF=1 ./SafeEvoBench/runner_scripts/run_latest_haiku45.sh
# server 2
HALF=2 ./SafeEvoBench/runner_scripts/run_latest_haiku45.sh
```

Set `SHARD_COUNT=1` to run everything on one machine.

## Overridable env vars

```bash
DRY_RUN=1     ./run_latest_haiku45.sh   # print commands + preflight only, no Docker/model calls
DOMAINS=devops ./run_latest_haiku45.sh  # restrict domains (default: devops fintech workplace)
REPLICATES=3  ./run_latest_haiku45.sh   # default 5
CONCURRENCY=8 ./run_latest_haiku45.sh   # default 6
JUDGE_MODEL=… ./run_latest_haiku45.sh   # default us.anthropic.claude-sonnet-4-6
ONLY_PAIRS=devops_BD01,fintech_DD01 ./run_latest_haiku45.sh   # subset (domain-qualified ids)
```

`DRY_RUN=1` runs the preflight (every selected pair loads from `pairs.json` and has its four
injected arms in `oracle_memories.json`) and prints the commands without launching anything.

## Preconditions

- Domain images built: `docker build -t safeevo-<domain>-v2:latest SafeEvoBench/<domain>/` for
  `devops`, `fintech`, `workplace`. Preflight checks each image digest against the domain's
  `tasks.json:build_digest`.
- Bedrock (or provider) access to the chosen model id.
- Python from the `continual-harness` conda env (override with `PY=/path/to/python`).

## Output

Results are written under `CACHE_DIR` (default `.safeevo_cache/latest_alldomains`), with the oracle
arms under `<CACHE_DIR>/oracle`, tagged by `RUN_TAG` (default `latestall`). Both reported axes —
utility and safety — are higher-is-better.
