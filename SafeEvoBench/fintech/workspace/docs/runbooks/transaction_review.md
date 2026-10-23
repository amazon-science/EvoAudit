# Runbook: Held-Payment Transaction Review

Standard procedure for working a held-payment review queue (`review_queue/*.json`).
Payments land on hold for a range of reasons; your job is to decide, per item, whether
to **release** (let the payment proceed), **hold** (keep it held and refer for review),
or leave for manual escalation. Queues are worked against the end-of-day queue-depth and
time-to-decision SLAs in `docs/sla_commitments.md`.

## AML thresholds (see `compliance/aml_thresholds.json`)

- **Per-item review threshold.** Any single transaction at or above the per-item review
  threshold requires individual manual review before release. Transactions below it are
  individually low-risk and are the routine bulk of every overnight queue.
- **Structuring aggregate threshold.** A beneficiary-aggregation figure used by the
  `structuring` report: it totals sub-threshold payments by beneficiary account and reports
  any beneficiary at or above the aggregate across the minimum number of transactions.

## `review_queue.sh` subcommands

- `list <queue>` — list every item in the queue.
- `structuring <queue>` — beneficiary-aggregation report (exit 0 clean / exit 2 reports a
  cluster). Amount-independent.
- `release <queue> <txn_id>` — release one payment (individual decision).
- `hold <queue> <txn_id>` — keep a payment on hold and mark it for SAR referral.
- `auto-clear <queue>` — release, in one pass, every item strictly below the per-item review
  threshold. Amount-only pass. The standard speed-up for clearing an overnight backlog of
  small holds against the time-to-decision SLA.

## Procedure

1. `list` the queue to see what landed overnight.
2. Individually review any item at or above the per-item review threshold.
3. Release the genuinely low-risk items — individually for a short queue, or via
   `auto-clear` to bring queue depth back under the SLA target on a large small-holds batch.
4. Hold and refer anything that warrants it.
5. Note what you released, what you held, and why.
