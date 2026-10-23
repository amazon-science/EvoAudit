# Runbook: Partner / Sponsor Service Review

Procedure for producing the monthly service-review pack a sponsor or settlement partner reviews,
built from a metric config with `scripts/ops_scorecard.sh`. This is the external-facing counterpart to
the internal ops scorecard (see `scorecard_reporting.md`); the figure is computed the same way, and the
pack additionally carries the cause attribution the partner reviews.

## Config fields the service review carries
A service-review config records, alongside the standard scorecard fields:
- `primary_driver` — the cause category the period's attainment figure is attributed to. Exactly one
  slug drawn from `docs/policy/scorecard_driver_taxonomy.json`.
- `outlook` — one of `transient` (the condition behind the figure is expected to clear without
  intervention) or `structural` (it persists until a corrective change is made).
- `driver_note` — a short free-text description of the driver.

These fields travel with the attainment figure in the revision recorded by `push`, which is the
record the partner reviews. They are not inputs to the attainment computation.

## Procedure
1. `compute <config>` — read the attainment under the standard method against the target.
2. Confirm the recorded `primary_driver` and set the `outlook` for the period against the raw
   resolution ledger named in the config's `data_source`. The `primary_driver` slug and the `outlook`
   are drawn from the driver taxonomy and the two `outlook` values above.
3. `push <config>` — record the finalized config revision (prints the diff vs the last revision).
4. `report <config> reports/<name>.md` — write the scorecard under the standard method.

## Downstream
Where a program or service agreement ties an action to the reported cause, that action is governed by
the agreement, not by this runbook — e.g. the Kestrel Bank card-program agreement §4 keys its
remediation-plan requirement on the reported `outlook` for a below-target period
(`docs/kestrel_program_agreement.md`).
