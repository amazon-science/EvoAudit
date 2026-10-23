# SafeEvoBench task-QA freezes

This directory implements the frozen-input and execution mechanism for the task
audit. The runnable auditor supports all three domains — `devops`, `fintech`, and
`workplace` — each of which is self-contained (a baked workspace served by local
engines, no live external services). Pair quality remains explicitly excluded.

## What is frozen

The freeze contains:

- task records, rubrics, evaluator code, Dockerfiles, and complete reset workspaces;
- shared authoring, protocol, schema, taxonomy, and task-QA specifications;
- the SafeEvoBench runner, continual harness, prompts, tools, dependency metadata,
  and tests;
- each regular file's raw bytes, executable mode, byte size, and SHA-256 digest;
- exact Docker image IDs, scenario-clock environment, embedded build digests, and
  a verified comparison between source files and files baked into each image;
- the runtime model/configuration choices and execution policy.

It excludes:

- `pairs.json` and pair-authoring inputs;
- `_fragments`, caches, bytecode, generated output, and OS metadata.

The output is:

```text
.safeevo_qa/freezes/<freeze_id>/
  freeze.json
  snapshot/
```

`freeze_id` is a SHA-256 content address over the immutable manifest body. Git
metadata is provenance only because the v2 bank may be untracked or the worktree
may be dirty.

## Create and verify

Run from the repository root:

```bash
python SafeEvoBench/qa/freeze_inputs.py create
python SafeEvoBench/qa/freeze_inputs.py verify \
  .safeevo_qa/freezes/<freeze_id>/freeze.json
python SafeEvoBench/qa/freeze_inputs.py verify \
  .safeevo_qa/freezes/<freeze_id>/freeze.json --check-worktree
```

Creation fails if a selected file is missing, pair-authoring data enters the
selection, task/rubric IDs disagree, an image build digest is wrong, or an
image's baked workspace differs from the selected source. Verification detects
missing, added, modified, or mode-changed snapshot files and rechecks executor
images by their immutable IDs.

`--skip-images` skips the executor image checks. It is only an offline
file-integrity check and is not sufficient before executing an audit.

## Source-complete versus audit-ready

The checked-in config pins the agreed study choices:

- auditor: `us.anthropic.claude-opus-4-8` (US inference profile for
  `anthropic.claude-opus-4-8`);
- blind actor: `moonshotai.kimi-k2.5`;
- fixed judge: `us.anthropic.claude-sonnet-4-6`;
- Bedrock region: `us-east-1`;
- base tool surface, planning off, fixed recognition-neutral framing;
- Anthropic prompt caching on and auditor message context capped at 140,000
  serialized characters.

The exact strings must pass Bedrock preflight; the runner never silently adds an
inference-profile prefix or substitutes an alias. Preflight requires an exact
`ok` response from all three models and an exact, forced preflight tool call
from both the auditor and blind actor. Normal audit turns do not force tool
selection. Opus 4.8 rejects the deprecated Bedrock `temperature` field, so the
frozen auditor temperature is `null`, which means the field is omitted; Kimi
and Sonnet remain explicitly pinned to `0.0`. A saved preflight record is
accepted on resume only when its region, model set, request temperatures,
prompt-cache write/read probes, and tool-use results still match the frozen run
manifest. Every resumed process also makes one fresh minimal request to each
pinned model before dispatch, so stale preflight evidence cannot mask expired
credentials or lost model access.

A freeze with an unresolved runtime field is source-complete but has
`full_audit_ready: false`. It can support static review and freeze-mechanism
testing. Because every domain is self-contained, a full audit needs only the
selected executor images:

```bash
python SafeEvoBench/qa/freeze_inputs.py verify \
  .safeevo_qa/freezes/<freeze_id>/freeze.json --require-full-audit
```

Do not fill these fields with aliases that can silently move to another model
version.

## Run task QA

Create a freeze after this audit implementation and the latest task changes are
present. The all-domain config covers `devops`, `fintech`, and `workplace`; a
scoped two-domain config is also available:

```bash
# all three domains
python SafeEvoBench/qa/freeze_inputs.py create

# devops + fintech only (excludes the workplace domain)
python SafeEvoBench/qa/freeze_inputs.py create \
  --config SafeEvoBench/qa/freeze_config_devops_fintech.json
```

The manifest records the repository-relative path and bytes of the config that
created it. Then preflight the exact frozen images and model IDs, and run the
audit with independent task workers:

```bash
python SafeEvoBench/qa/run_task_audits.py \
  --freeze .safeevo_qa/freezes/<freeze_id>/freeze.json \
  --domains devops fintech workplace \
  --preflight-only

python SafeEvoBench/qa/run_task_audits.py \
  --freeze .safeevo_qa/freezes/<freeze_id>/freeze.json \
  --domains devops fintech workplace \
  --max-workers 2
```

Results are written under
`.safeevo_qa/audits/<freeze_id>/<audit_run_id>/`. Reusing the same
`--audit-run-id` preserves completed `PASS`/`FAIL` findings and
spec-conflict-only `NOT_VERIFIED` findings. Results containing audit errors or
unfinished/error checks are archived under `failed_attempts/` and rerun. Each
task gets an isolated Opus context, a separately blinded Kimi smoke run, fresh
no-egress containers for every arm, and three independent Sonnet judgments of
refusal, safe, and unsafe/affordance transcripts. `aggregate.json` and
`aggregate.md` are computed from validated per-task JSON; model-written counts
are never used.

The Opus system/tools and per-task package are explicit cache prefixes. Each
immutable judge trajectory is a Sonnet cache prefix shared by both axes and all
replicates. Cache writes and reads are usage optimizations only: the full prompt
text remains persisted, and responses, strict parsing, repetitions, and stored
evidence follow the same contracts.

For file-only inspection of an older source-complete freeze:

```bash
python SafeEvoBench/qa/run_task_audits.py \
  --freeze .safeevo_qa/freezes/<freeze_id>/freeze.json \
  --domains devops fintech workplace --offline-check
```

Offline checking does not authorize acting runs.

Before any live dispatch, the runner also requires every official audit source
file in the freeze and compares its frozen file record with the current
worktree byte-for-byte, including mode. Any implementation or test change
requires a new freeze; a stale freeze cannot authorize an official run.

Static validators run against a disposable copy of the snapshot. The repository
rubric linter is retained, but because pair files are intentionally excluded its
`rubrics authored: 0/0` output is marked vacuous. A separate QA-owned lint
validates the selected task and rubric directly (`1/1`), including criterion
shape and IDs, taxonomy metadata, supported state checks, snapshot paths, and
cross-task criterion-ID collisions. Frozen evaluator modules are compiled from
their recorded bytes without loader-based imports, so static inspection cannot
write bytecode into the immutable snapshot.

## Worker contract

Every audit worker must:

1. verify `freeze.json`, the selected images, selected-domain readiness, and
   exact frozen model/config choices;
2. read task, rubric, workspace, evaluator, and checklist files only from
   `snapshot/`;
3. launch the domain image using the manifest's `image_id`, never its tag;
4. start every arm from a fresh disposable reset and deny task-container egress;
5. write trajectories, state captures, evidence, and verdicts outside `snapshot/`;
6. record `freeze_id`, task ID, arm/reset ID, acting model, auditor model, judge
   model, and effective agent configuration in every result.

If `--check-worktree` fails after authoring changes, do not update an existing
freeze. Create a new one. Old result files remain bound to their original
`freeze_id`.

Docker image IDs pin the observed state on one daemon but do not archive image
layers. Before a long audit, retain images in an access-controlled registry by
digest or export them as OCI/Docker archives, and record those retention
locations with the audit run.
