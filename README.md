# EvoAudit

EvoAudit is the code and benchmark for measuring **co-evolution safety**: does an LLM agent's runtime
self-evolution (memory, skills, subagents) change its behavior as it carries experience from a
*source* task into a *target* task? Every run is scored on two axes, both higher-is-better:

- **Utility**: task completion.
- **Safety**: `1 - rubric harm` (1.0 means no hazard).

The benchmark is a set of source-to-target task **pairs** in three self-contained domains:

| Domain | Tasks | Pairs |
|---|---|---|
| `devops` | 80 | 48 |
| `fintech` | 33 | 40 |
| `workplace` | 42 | 54 |

An **agent** model runs each pair's arms (cold and evolved), and a separate **judge** model scores
both axes.

This code is being released solely for academic and scientific reproducibility purposes, in support of the methods and findings described in the associated publication. Pull requests are not being accepted in order to maintain the code exactly as it was used in the paper.

## Disclaimer

Synthetic Content Disclaimer. All names, organizations, domain names, characters, records, and scenarios in this benchmark are entirely fictional. They were synthetically generated with an LLM coding agent; the workplace domain also adapts the fictional company, names, and task structure of TheAgentCompany (Xu et al., 2024), itself a synthetic benchmark. Fixtures resembling operational records (deletion lists, legal holds, watchlists, KYC files, contracts) contain no real data. Any resemblance to real persons, companies, products, or events is coincidental and unintended. The scenarios are designed exclusively for evaluating how runtime self-evolution affects the safety and utility of LLM agents and do not represent endorsements, accusations, or characterizations of any real entity.

## Repository layout

| Path | Contents |
|---|---|
| `SafeEvoBench/` | The benchmark bank and its tooling. The folder keeps its original name so paths match the paper. |
| `SafeEvoBench/{devops,fintech,workplace}/` | One self-contained domain each: `tasks.json`, `pairs.json`, `oracle_memories.json`, `allocation.json`, `evaluation/` (rubrics, `evaluate.py`, scorers), `workspace/` (fixtures and local engines baked into the image), `Dockerfile`. |
| `SafeEvoBench/*.md`, `taxonomy.json` | Normative specs: `TAXONOMY.md`, `SCHEMA.md`, `PROTOCOL.md`, `PROVENANCE.md`, `AUTHORING_RULES.md`, `RESULTS_SPEC.md`, `QUALITY_ASSURANCE_CHECKLIST.md`. |
| `SafeEvoBench/validate_bank.py` | Bank validator (also `check_leaks.py`, `check_baseline.py`, `evaluation_contract.py`). |
| `SafeEvoBench/qa/` | Freeze/reproducibility tooling and the LLM task-quality audit. |
| `SafeEvoBench/runner_scripts/` | The `run_latest_<model>.sh` experiment wrappers, the shared `_common_*.sh` drivers, and `run_memory_oracle.py` (oracle injected-memory arms). |
| `benchmarks/safeevobench/` | The run harness: `run.py` (single run), `run_pairs.py` (pair matrix, the runner entry point), `run_cold.py`, `run_factorial.py`, `adapter.py`, `tools.py`. |
| `continual_harness/` | The agent harness (memory, skills, subagents stores and evolvers). |
| `tests/` | pytest suite covering the bank, evaluators, QA tooling and harness. |

## Setup

1. Create the Python environment (env name `continual-harness`, Python 3.11):

   ```bash
   conda env create -f environment.yml
   conda activate continual-harness
   ```

   Run everything **from the repo root**. `benchmarks/`, `continual_harness/` and `SafeEvoBench/`
   are imported as local packages; nothing is pip-installed.

2. For real runs, install Docker and build each domain image:

   ```bash
   docker build -t safeevo-devops-v2:latest    SafeEvoBench/devops/
   docker build -t safeevo-fintech-v2:latest   SafeEvoBench/fintech/
   docker build -t safeevo-workplace-v2:latest SafeEvoBench/workplace/
   ```

   Before a real run, the preflight checks that each image's `/etc/img_build.digest` matches
   `build_digest` in `SafeEvoBench/<domain>/tasks.json` and stops if they differ.

## Quality checks

None of these need Docker or model access.

```bash
python SafeEvoBench/validate_bank.py            # expect "OK: 0 errors" (warnings are advisory)
python -m pytest tests/ -q                      # expect all tests to pass
DRY_RUN=1 SHARD_COUNT=1 ./SafeEvoBench/runner_scripts/run_latest_haiku45.sh   # preflight only
```

The dry run prints the commands it would run and should report 48 devops, 40 fintech and 54
workplace pairs selected, with injected arms present.

## Running

Models are called through Amazon Bedrock. Use your own AWS credentials with access to the agent
and judge models (any standard AWS credential source works; `AWS_PROFILE` is forwarded if set),
and set `AWS_REGION=us-east-1`. The `us.*` model ids are cross-region inference profiles and need a
US region.

### One-pair smoke run

One pair, one config, one replicate, no oracle arms; Haiku 4.5 agent and Sonnet 4.6 judge:

```bash
AWS_REGION=us-east-1 DOMAINS=devops ONLY_PAIRS=devops_BB01 \
  CONFIGS=memory REPLICATES=1 RUN_INJECTED=0 SHARD_COUNT=1 \
  ./SafeEvoBench/runner_scripts/run_latest_haiku45.sh
```

This takes a few minutes. Success is a log line `Wrote .../collective_results.json (1 pairs)` and
exit code 0. With one replicate both arms are scored but the delta is reported as `unscored` (see
below).

### Full run

```bash
AWS_REGION=us-east-1 SHARD_COUNT=1 ./SafeEvoBench/runner_scripts/run_latest_haiku45.sh
```

The default scope is all three domains, the newest variant of each pair (`PAIR_SET=latest`), the
8-config evolution matrix (`memory skills subagents evolve meta_memory meta_skills meta_evolve
base`) plus the oracle injected-memory arms, and 5 replicates. That is 142 pairs x 8 configs x 5
replicates x 2 arms, plus the oracle arms, so narrow it with `DOMAINS` / `ONLY_PAIRS` first or
split it across two machines.

The wrappers default to `SHARD_COUNT=2`. Set `SHARD_COUNT=1` to run everything on one machine, or
run `HALF=1` on one machine and `HALF=2` on another; both halves share `RUN_TAG`, so their results
aggregate as one batch once copied into one `CACHE_DIR`.

### Agent models

One wrapper per agent model, in `SafeEvoBench/runner_scripts/`. The judge defaults to
`us.anthropic.claude-sonnet-4-6` for all of them.

| Wrapper | Agent model id |
|---|---|
| `run_latest_haiku45.sh` | `us.anthropic.claude-haiku-4-5-20251001-v1:0` |
| `run_latest_sonnet46.sh` | `us.anthropic.claude-sonnet-4-6` |
| `run_latest_kimi.sh` | `moonshotai.kimi-k2.5` |
| `run_latest_qwen_next80b.sh` | `qwen.qwen3-next-80b-a3b` |
| `run_latest_gpt_oss_120b.sh` | `openai.gpt-oss-120b-1:0` |
| `run_latest_gpt5_6_luna.sh` | `us.openai.gpt-5.6-luna` |
| `run_latest_llama3_3_70b.sh` | `us.meta.llama3-3-70b-instruct-v1:0` |
| `run_latest_glm5.sh` | `zai.glm-5` |
| `run_latest_devstral.sh` | `mistral.devstral-2-123b` |

### Environment knobs

All are optional and read from the environment.

| Variable | Default | Meaning |
|---|---|---|
| `DOMAINS` | `devops fintech workplace` | Domains to run. |
| `ONLY_PAIRS` | (all selected) | Comma-separated, domain-qualified pair ids, e.g. `devops_BB01,fintech_DD01`. |
| `CONFIGS` | the 8 matrix configs | Evolution-matrix cells to run. |
| `REPLICATES` | `5` | Replicates per arm. |
| `RUN_MATRIX` / `RUN_INJECTED` | `1` / `1` | Run the evolution matrix / the oracle injected-memory arms. |
| `JUDGE_MODEL` | `us.anthropic.claude-sonnet-4-6` | Judge model id. |
| `CONCURRENCY` | `6` | Parallel arms per run. |
| `HALF` / `SHARD_COUNT` | `1` / `2` | Which half to run, and how many shards to split the pairs into. |
| `RUN_TAG` | `latestall` | Batch tag; reuse it to resume. |
| `CACHE_DIR` | `.safeevo_cache/latest_alldomains` | Where results are written. |
| `DRY_RUN` | `0` | `1` prints the commands and runs the preflight only. |

Deltas (cold vs. evolved) need at least 2 **disjoint** replicates; see
`SafeEvoBench/RESULTS_SPEC.md`.

## Results

Results go under `CACHE_DIR` (default `.safeevo_cache/latest_alldomains/`, gitignored), with the
oracle arms under `<CACHE_DIR>/oracle/`. Each batch is a directory
`<domain>_<model>_<config>_<RUN_TAG>/` holding one subdirectory per pair (its `cold/` and `evolve/`
arms) and a `collective_results.json` summary of per-pair cold, evolved and delta scores. Runs are
resumable: rerun the same wrapper with the same `RUN_TAG` and completed arms are reused.

To clean up after a run, remove stray containers listed by `docker ps | grep safeevo`.

## Notes

- **Executor sandbox.** Each executor container runs an HTTP API that executes the agent's shell
  commands without authentication; that is the agent's tool sandbox. The harness publishes it on
  `127.0.0.1` only. Don't publish it on other interfaces, and run on a machine you control.
- **TheAgentCompany live services.** `run.py`, `run_pairs.py` and `run_cold.py` have options
  (`--service-*`, `--lanes`) for connecting the workplace executor to live TheAgentCompany
  services. They are off by default and were not used in the paper. The `SafeEvoBench/tac/ops/`
  scripts mentioned in their help text are not included.
- **Changes after the paper.** Relative to the code used for the paper, this release changes only
  documentation and comments, the default interpreter in `run_memory_oracle.py` (now `$PY` or the
  current Python), and the executor port mapping in `run.py` (now published on `127.0.0.1` only).
  No image contents, tasks, rubrics, prompts or harness logic changed.

## Third-party code

- `continual_harness/` is derived from
  [sethkarten/continual-harness](https://github.com/sethkarten/continual-harness) (MIT).
- The `workplace` domain adapts the fictional company, names and task structure of
  [TheAgentCompany](https://github.com/TheAgentCompany/TheAgentCompany) (MIT).

See [THIRD-PARTY-NOTICES.txt](THIRD-PARTY-NOTICES.txt) for the full license texts.

## Citation

> **TODO:** add the BibTeX entry once the paper is on arXiv.

## License

This project is licensed under the Creative Commons Attribution-NonCommercial 4.0 International
License (CC BY-NC 4.0). See [LICENSE](LICENSE) and [NOTICE](NOTICE).
