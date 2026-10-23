# Chargeback Operations — June 2024 period digest

Routine end-of-period notes for the Chargeback Operations queue. Compiled for the internal ops
review; figures below are period counts, not SLA attainment (see the scorecard configs for that).

- Inbound dispute intake was up roughly 22% month-over-month, continuing the trend since the
  card-network representment-window change that took effect 2024-05-20. Intake is expected to settle
  toward the trailing baseline over the next one to two cycles as issuers work through the backlog.
- Two manual-evidence reviewers were on planned leave for part of the month (one for the last two
  weeks); the temp backfill covered intake triage but not representment evidence work.
- The dispute-intake tooling migration to the new case UI completed on 2024-06-09 with no rollback.
- The nightly acquirer settlement feed had a scheduled maintenance window on 2024-06-22; no cases
  missed a cutoff as a result.
- Category mix was broadly in line with May: fraud and product-not-received remained the two largest
  reason-code buckets.

Nothing on this digest is tied to a specific SLA metric; the resolution-time attainment figures are
computed from the resolution ledger under each metric config.
