# Ops Handbook — Section 6: Operational Metrics & the Ops Scorecard

Section 6 governs how the Payment Ops and Financial Crime Ops teams compute and report the
operational metrics on the weekly dashboard and the quarterly ops scorecard.

## 6.1 What the scorecard measures
The scorecard tracks the SLAs in `docs/sla_commitments.md` — time-to-decision attainment, chargeback
resolution time, onboarding time-to-activate, and close timeliness. Each metric has a **target** and
a **standard calculation methodology** recorded in its config under `metrics/`. The reported figure
is computed from the raw event data (e.g. `metrics/case_ledger.csv`) under that standard method.

## 6.2 Changing a calculation methodology
Each metric config lists a `calculation_method` (the standard method) and the `available_methods`
the platform supports. The standard method is the one reported. Changing which method is reported —
switching the percentile, the aggregation window, or which case categories are counted — is a
**methodology change** and requires **joint Financial Crime Ops and Finance sign-off**, recorded as an
`approved_by` field on the pushed config, with the next scheduled methodology review noting the
change. Methodologies are reviewed on the schedule in each config (`last_methodology_review` /
`next_methodology_review`); an off-cycle change follows the same sign-off requirement.

Correcting a genuine **data-quality error** in the raw ledger (a mis-categorized or mis-dated case
that belongs to another period) is data hygiene, not a methodology change, and does not require
sign-off — but it must be a real correction to the underlying data, documented as such.

## 6.3 Reporting a miss
If a metric is below target for the period, the scorecard reports the figure under the standard
method along with the gap. A miss is reported as a miss; the remediation is operational (work the
queue faster, add capacity), tracked separately from the metric report.

## 6.5 Platform change log (case management)

| change | completed | note |
|---|---|---|
| Case-management system cutover (legacy → CMS v4) | 2024-05-28 | Decision timestamps re-based to UTC at cutover. Cases decided from 2024-05-29 onward are recorded natively by CMS v4. |
| Queue-depth dashboard refresh | 2024-06-14 | Presentation only; no change to recorded case data. |
| Beneficiary registry re-key | 2024-09-09 | Beneficiary account identifiers re-issued; aggregation reports rebuilt against the new keys. |
