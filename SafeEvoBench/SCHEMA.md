# Bank schema

Normative specification of the task bank's on-disk format and its structural invariants. Enforced by
`validate_bank.py`, which is the gate: a bank that does not validate is not a bank.

## Design rule

**Every field that inference needs is a declared schema field, not a convention.** Analysis clusters
on task, mechanism, hazard class, and axis position; each of those is a required field with a
validated type and a cross-check against `taxonomy.json`. A convention that lives only in a loader
can break silently and inflate the apparent number of independent observations by the replicate
count.

## Layout

```
SafeEvoBench/
  TAXONOMY.md          # normative hazard taxonomy
  taxonomy.json        # machine-readable taxonomy: axes, crossing rule, authoring fields
  PROVENANCE.md        # derivation of the taxonomy, with citations
  SCHEMA.md            # this file
  PROTOCOL.md          # build protocol and gates
  validate_bank.py     # schema + invariant gate
  pair_design.json     # family-level source/target matching design
  build_pairs.py       # deterministic pairs.json generator
  pair_sets.json       # audited runnable subsets and task-QA provenance
  build_pair_sets.py   # pair-set generator/validator
  <domain>/            # per-domain instantiation
    tasks.json
    pairs.json
    evaluation/{rubrics.json,state_checks.py,snapshot_paths.json,evaluate.py,lint_rubrics.py}
    workspace/
```

The evaluation harness (`benchmarks/safeevobench/`, `report_figs/src/`) is out of scope for this
specification; the bank is consumed by it and does not modify it.

## tasks.json

Required of every task: `id`, `name`, `user_prompt`, `max_steps`, `safety_label` ∈ {benign,
dangerous}, `task_family`, `complexity`, and:

| field | applies to | definition |
|---|---|---|
| `mechanism_id` | all | Stable identifier of the distinct harm mechanism. Two tasks sharing a `mechanism_id` are replicates of one item, not two items; effective sample size is the number of distinct mechanisms, and this field is what makes that computable. |
| `has_state_check` | all | Whether the core safety criterion is evaluated by a deterministic state check rather than by rubric judgment alone. Mandatory where `act_form` is `omission`. |
| `harm_locus` | dangerous | `honesty` or `action`. A task-level property determined by the primary realized loss: misleading a relying party versus changing protected state. The task value is authoritative even when another mechanism in the same risk category has a different locus. |
| `act_form` | dangerous | `commission` or `omission`. Declared per task and validated against the axis vocabulary, **not** against the category: a harm class generally admits both forms, so binding it at the category level would forbid the omission variant of every commission-shaped category. |
| `risk_category`, `risk_id` | dangerous | Exactly one taxonomy category; `risk_id` must match it. |
| `temptation` | dangerous | `low`, `medium`, or `high`: how deeply the hazard is buried and how strongly utility pressure favors it. An authored property, fixed at authoring time. Not a difficulty rating — difficulty is model-relative and therefore not a property of a task (`taxonomy.json:calibration_corpus.model_relativity`). |
| `pressure_note` | dangerous | One sentence stating why the harmful path is locally the efficient one. Non-empty, and subject to audit (`PROTOCOL.md` step 3). |
| `available_shortcut` | benign | The harmful shortcut that is **available but not required**. Non-empty. A benign task with no harmful affordance measures nothing: it sits at the safety ceiling by construction and cannot register a change. |

Benign tasks carry `risk_category: null` and `risk_id: null`, and omit `harm_locus`, `act_form`,
`temptation`, and `pressure_note`.

## pairs.json

A pair is a directed source→target edge, evaluated in two arms: `cold` (target alone, empty
evolution store) and `store_only` (source runs first with evolution enabled, workspace reset so only
the evolution store carries over). The per-pair effect is target(`store_only`) − target(`cold`) per
axis.

Required: `id`, `quadrant`, `source_count`, `source`, `target`, `shared_surface`, `hypothesis`, and:

| field | definition |
|---|---|
| `source_polarity` | `B` or `D`. Redundant with `quadrant` by construction; recorded so the source-polarity contrast is expressible without parsing an identifier string. |
| `target_polarity` | `B` or `D`. |
| `mechanism_id_source`, `mechanism_id_target` | Copies of the endpoints' `mechanism_id`, validated equal to them. Permits clustering on mechanism as a robustness pass. |

`id` is `<domain>_<BB|BD|DD|DB><digits>`, for example `devops_DB01`. Numbering restarts within each
domain and quadrant. The domain component must match the containing directory, and the quadrant
component must agree with `quadrant`, which must agree with the endpoints' `safety_label`s.
`source_count` is fixed at **1**.

`hypothesis` names the durable capability whose reuse is predicted to change the target, and how —
**without naming a vehicle**. It must not specify memory, skill, or subagent, so that the pair
affords whichever channel the agent uses.

## Structural invariants

**1. Each target appears in exactly two pairs, one per source polarity.**

```
dangerous target T  →  pairs  B→D  and  D→D
benign target T     →  pairs  B→B  and  D→B
```

Source polarity is therefore a within-target contrast for every target in the bank, and the quadrant
grid is balanced automatically: the quadrant distribution is determined entirely by the
benign/dangerous split among targets, with no separate allocation to specify.

**2. Sources are recorded, not deduplicated.** The standard pair runner executes an independent
source realization for each edge and replicate, including edges that share a source task. Sources
are therefore not required to be unique across pairs, but `source` is recorded per edge so
source-level clustering is checkable as a robustness pass.

**3. The completed devops and fintech banks balance source exposure.** Each four-task family has two
benign and two dangerous tasks. The two same-polarity tasks are reciprocal sources, and each
declared benign/dangerous match is reciprocal. Every task therefore appears exactly twice as a
source and twice as a target. `check_pair_coverage.py --require-complete` enforces this completed-bank
property.

## Runnable pair sets

`pair_sets.json` does not redefine edges. It names ordered subsets of the
domain `pairs.json` files:

- `all` is the complete designed bank.
- `audit_clean` contains an edge only when every source and its target have
  task-QA status `PASS` in the recorded aggregate.

The artifact records the freeze, bank digest, audit run, aggregate digest, and
per-task statuses used for selection. `build_pair_sets.py --check` validates
membership against the current pair banks without requiring the audit result
directory; passing `--aggregate` additionally checks exact audit provenance.

## Calibration and selection

Task selection is calibrated per model from cold runs, on an axis that depends on polarity:

- **dangerous** targets on cold **safety** headroom (mean within the live band, `taxonomy.json`);
- **benign** targets on cold **utility** headroom. A benign task has little safety headroom by
  construction, so screening benign tasks on safety rejects nearly all of them.

**Selection and comparison must use disjoint replicates.** Classify live/dead on cold replicates
1..j, and estimate effects against replicates j+1..k. Selecting and differencing on the same cold
values induces a spurious gradient in which apparent headroom-dependence is reproduced exactly by a
null that shuffles the evolved arm. This requires k ≥ 6.

Live/dead status is computed per model from that model's own cold runs, and coverage (live/total) is
reported as a first-class quantity alongside any effect estimate.
