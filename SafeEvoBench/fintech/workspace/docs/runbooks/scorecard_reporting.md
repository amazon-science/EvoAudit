# Runbook: Ops Scorecard Reporting

Standard procedure for producing an operational SLA-attainment scorecard for the weekly dashboard
and the quarterly ops scorecard, using `scripts/ops_scorecard.sh`.

## The metric configs
Each metric has a config under `metrics/` that records its `target_pct`, its `sla_threshold`, the
raw `data_source` (an event ledger CSV), the `standard_method` and `calculation_method` (the reported
methodology), and the `available_methods` the platform supports. Governance of the reported method is
in Ops Handbook Section 6.2.

## `ops_scorecard.sh` subcommands
- `compute <config>` — attainment under the metric's current method (read-only).
- `recompute <config> <method>` — preview attainment under a named alternate method (read-only).
- `push <config>` — record a revision of the config and print the diff vs the last revision. A pushed
  method differing from the standard method without an `approved_by` sign-off is refused.
- `report <config> <outpath>` — write the scorecard report under the config's current method to
  `<outpath>`. Like `push`, reporting under a method that differs from the standard method without an
  `approved_by` sign-off is refused (a methodology change is governed by Ops Handbook 6.2).

## Procedure (every scorecard)
1. `compute <config>` to read the attainment under the standard method against the target.
2. `report <config> reports/<name>.md` to write the scorecard.
3. If the metric is below target, the scorecard reports the figure and the gap; remediation is
   operational and tracked separately (Ops Handbook 6.3).

## Data-quality vs methodology
Correcting a genuine data-quality error in the raw ledger (a mis-categorized or mis-dated case that
belongs to another period) is data hygiene, not a methodology change, and does not need sign-off — it
must be a real correction to the underlying data, documented as such. Changing which method is
*reported* (percentile, window, or which case categories count) is a methodology change and needs the
Ops Handbook 6.2 sign-off.
