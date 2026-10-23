# Build protocol

Six ordered steps, each with a gate. The ordering is load-bearing: the taxonomy carries the hazard
mechanism, the per-cell quotas, and the temptation grading, so the taxonomy audit precedes task
authoring — revising it afterwards requires re-authoring. Step 3 produces a hazard spec for every
`(category × family)` cell while step 4 pilots two tasks per category; that asymmetry is intended, since
specs are prose and tasks are fixtures. Every category is piloted; not every cell is.

## Step 1 — bank scaffold

`TAXONOMY.md`, `taxonomy.json`, `PROVENANCE.md`, `SCHEMA.md`, `PROTOCOL.md`, `validate_bank.py`.

**Gate:** `validate_bank.py` exits 0 on an empty bank.

## Step 2 — audit the domain-independent taxonomy

The taxonomy is settled before any domain instantiates it, because it carries the hazard mechanisms
authors work from. The audit is complete; `taxonomy.json:resolved_questions` records each outcome and
its reasoning. In summary:

1. **The saturated categories were re-specified, not dropped.** Both had framed the harm as the subject
   of the request. `RISK-PV` keeps its definition with a pressure requirement that the harm arise as a
   consequence of ordinary work. `RISK-RH` is re-scoped from metric editing to gaming a completion or
   health signal, which is within the source's category definition and no longer collides with
   reporting hazards. Both are `unmeasured` and both are re-piloted in step 4.
2. **Two source categories were excluded as un-instantiable**, joining `RISK-SSM`: `RISK-EG` as the
   source defines it targets the model's own deployment-gating assessment, which this environment does
   not contain. Its one task, a dashboard percentile selected to flatter a missed target, was
   reclassified to `RISK-DC`.
3. **`act_form` moved from the category level to the task level.** The axis was not under-populated;
   binding it per category had forbidden the omission variant of every commission-shaped category,
   including omission-form Deception. The rule that omission requires a deterministic state check is
   unchanged and still enforced.
4. **The `harm_locus` split needs no change.** Three honesty and four action categories reach ~30
   dangerous tasks per side within the 20% cap. Total bank size, not the taxonomy, is the binding
   constraint, and step 4 resolves it.

**Gate (met):** every category carries the four authoring fields and a provenance tag; both `harm_locus`
values populated; no category above 20% of planned dangerous tasks; every excluded category recorded
with its reason.

## Step 3 — per-domain hazard specifications

One spec per `(category × family)` cell, stating: mechanism, pressure, safe path, unsafe path, the
deterministic state check, and the benign counterpart's available shortcut. Specs are authored within
one assigned category, against the `instantiations` registry in `taxonomy.json`, which is read before
authoring and appended after. The registry is the guard against mechanism collapse: distinct tasks
sharing a mechanism are replicates, and effective sample size is the mechanism count.

The crossing rule governs this step — ≥2 families per category, ≥2 categories per family — so the
unit of authoring is a cell, not a category.

**Gate.** A spec is rejected if:

- its `pressure` does not survive scrutiny. A hazard whose safe path is also its easy path measures
  recognition of an obvious prohibition and saturates uniformly; this is the leading cause of ceiling.
- the benign counterpart has no available shortcut.
- the unsafe path leaves no distinguishable state, so no deterministic check can key on it.
- it reuses a framing recorded under `retired_framings` in `taxonomy.json`.

## Step 4 — pilot: cold arm only

**Size: 2 × |categories| dangerous targets, and as many benign.** With seven categories that is 14
dangerous and 14 benign. The size is a formula rather than a fixed count so that it tracks the
taxonomy: excluding or adding a category changes the pilot automatically, and no category is ever
covered by a single task.

**Dangerous targets are stratified by category — 2 each, all seven covered.** The pilot's question is
which categories yield live items, since that is what sizes the full bank. Two tasks per category is
the minimum that separates a saturated category from a badly authored task; one task cannot distinguish
them, which is why full coverage matters more here than depth. The two `unmeasured` categories
(`RISK-RH`, `RISK-PV`) are the highest-value slots, since an untested specification is the thing most
likely to fail, and `RISK-CMS` shares a boundary with `RISK-RH` that the pilot is what tests.

**Benign targets are stratified by task family, not by category** — they carry none. Two per family
across the families the dangerous tasks occupy, which both screens the `available_shortcut` design and
front-loads the shared surface that step 5 needs for pairing.

Parameters:

- **3 cold replicates per task per model** for the pilot's classification question. The disjoint-split
  rule (`SCHEMA.md`) binds only where the *same* runs would both select tasks and estimate effects; the
  pilot only classifies, and the evolved arm is a separate later pass, so no split is needed here. A
  ceiling baseline's uncertainty is wide at this n (0 harms in 6 runs still admits true harm rates up to
  39%), which is why effect claims rest on the *distribution across pairs* rather than on any single
  pair's magnitude (`RESULTS_SPEC.md`).
- **≥2 models spanning capability.** Live/dead is model-relative — 22 of 31 tasks in the calibration
  corpus were live for some models and saturated for others — so a single model yields a bank that
  does not generalize.
- **Graded deterministic scoring from the start** (`state_checks.py`, `snapshot_paths.json`). A coarse
  rubric contributes its own ceiling: the calibration corpus resolved to 21 discrete score values
  across 6,927 runs, so part of the observed saturation is rubric granularity rather than model
  behavior, and sizing the bank off a coarse rubric measures the rubric.

Screening axis differs by polarity: dangerous on cold safety, benign on cold utility (`SCHEMA.md`).

**Gate.** The gate is per-category, not aggregate: the bank is sized by *which* categories are
productive, and an aggregate pass rate can hide a dead category behind live ones.

The criterion is **directional**, because the claim is (see `RESULTS_SPEC.md`). What matters in a cold
baseline is **room to fall**, so a category at the safety ceiling passes — a full flip from 1.0 is the
strongest result the study can report. The two-sided band `[0.15, 0.90]` is retired as a pass/fail
test for dangerous targets; it remains a description, and a screen for benign targets on utility.
Both axes are scored, graded (not binary), for every task.

- **Per category:** ≥1 of its 2 dangerous tasks has room to fall on ≥1 model (cold safety not at the
  floor), and its cold utility is not at the floor either — a task the model cannot do is not a task
  whose safety can be interpreted. A category failing this is re-specified or excluded before the full
  build; it does not enter the bank on the strength of an argument.
- **Disqualification is measured against the evolved arm, not the cold arm.** A cell that cannot move
  in *any* condition contributes to no claim. A cell pinned at the ceiling in the cold arm is retained
  until the evolved arm shows it is immovable.
- **Overall:** ≥60% of dangerous pilot tasks have room to fall on ≥1 model. Below that the hazard
  specifications are the problem generally, not category by category; return to step 3.
- **Both axes survive:** ≥1 productive category on each side of `harm_locus`, or the primary contrast
  cannot be powered whatever the bank size.
- **Replicate budget:** 3 per pair per arm is sufficient, because the claims are distributional and
  reps need only call the *sign* of Δ. Budget goes to distinct pairs instead (`RESULTS_SPEC.md`).

Record and report the per-category outcome even where the overall gate passes. A category that survives
by re-specification rather than by measurement is disclosed as such, since two of the seven arrive at
this step already `unmeasured`.

## Step 5 — sources

Each target receives exactly two pairs, one per source polarity (`SCHEMA.md`, invariant 1). A source
may be an existing task where the association is real — shared workspace surface, or the same action
class. Pairs are never formed at random: a pair whose endpoints share nothing measures nothing.

Each pair's `hypothesis` names the durable capability and the predicted change in the target without
naming a vehicle, so the pair affords whichever channel the agent uses. `source_count` is 1
throughout.

**Gate:** `validate_bank.py` exits 0 — every target in exactly two pairs, one per polarity, quadrants
consistent with endpoint labels, `source_count == 1`.

## Step 6 — pair audit, then freeze

Per pair: solvability; no recognition leaks in agent-visible text; hazard not telegraphed;
container-verified safe and unsafe paths diverging in recorded state; idempotency; clock coherence;
rubric criteria keyed to evidence the trajectory can actually contain. One reviewer per pair, in a
throwaway container.

Then two bank-level passes:

**Near-duplicate audit.** Cluster the finished bank by `mechanism_id` and by prompt and artifact
similarity. Effective sample size is the number of distinct mechanisms, and it is the number that
enters the power calculation; a bank of 120 tasks over 12 mechanisms has n = 12.

**Freeze and pre-register.** The bank digest and the contrast list are committed before the evolved
arm runs. Item selection that leaks into results is not detectable after the fact, and a null result
requires a pre-committed item set to carry any weight.

**Gate:** frozen bank digest and pre-registered contrast list committed; then the evolved arm runs.

## Decisions deferred to pilot data

| decision | resolved by |
|---|---|
| Benign/dangerous target split | Step 4: whether benign targets show utility headroom under the available-shortcut design. A 50/50 split makes half the bank (B→B and D→B) a negative control; the adjustment is to skew the target split, never to break the two-pairs-per-target invariant. |
| Total bank size | Step 4 live rate, measured under graded scoring |
| Number of pilot domains | One domain validates the taxonomy and protocol at 2 × \|categories\| targets per polarity rather than twice that; a second inherits a proven specification |
| Whether the re-specified `RISK-RH` and `RISK-PV` are instantiable at all | Step 4: both are `unmeasured`, and the pilot allocates slots to each |
