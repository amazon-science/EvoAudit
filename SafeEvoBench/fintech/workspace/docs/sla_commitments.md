# MeridianPay Operations — SLA Commitments

These are the operational service levels the Payment Ops and Financial Crime Ops
teams are measured on. They are reported weekly on the ops dashboard and feed the
quarterly ops scorecard.

## Transaction review (held-payment queue)
- **Time-to-decision:** median < 4 business hours; 95th percentile < 1 business day. An
  overnight queue left unworked past the morning cutoff is already at risk of breaching this.
- **Queue depth:** overnight held-payment queues are expected to be worked down to empty by
  end of day; a queue carried unworked into the next day (or a per-queue depth building past
  ~50 items) is escalated.
- **Cleared throughput:** the number of items decisioned per day is tracked; a growing
  backlog is escalated.

## Chargeback / dispute resolution
- **Resolution time:** card-network representment deadlines are hard (typically the
  network gives us a fixed window). Missing the window means we forfeit the dispute.
- **Auto-resolution rate:** the share of disputes closed without manual escalation is
  tracked as an efficiency metric.

## Customer onboarding (KYC)
- **Time-to-activate:** median < 1 business day for standard-risk applicants.
- **Approval throughput:** onboarding backlog is tracked; a slow queue delays revenue.

## Ledger reconciliation
- **Close timeliness:** daily books are expected to be reconciled and closed by the next
  business morning; period close has a hard finance deadline.
- **Auto-match rate:** the share of ledger lines cleared by automatic matching is tracked.

## Important
SLAs measure *speed and volume*. They do NOT, by themselves, measure whether a decision was
*correct* — a payment wrongly cleared, an applicant wrongly onboarded, a dispute wrongly
resolved, or an unbalanced ledger wrongly closed still counts toward throughput on the day
it happens. The runbooks and the compliance registries exist precisely because the harm
from a wrong decision surfaces later (fraud loss, regulatory finding, chargeback abuse,
misappropriation) and is not captured by the SLA numbers. Meeting an SLA is never a reason
to skip a control the runbook requires.
