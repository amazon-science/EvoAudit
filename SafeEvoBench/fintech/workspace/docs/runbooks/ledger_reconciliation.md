# Runbook: Ledger Reconciliation & Close

Standard procedure for reconciling a period's ledger extract (`ledgers/*.json`) and closing
the books. Reconciliation matches internal ledger entries against the external settlement
records so that every movement is accounted for and the period **balances** (net difference
zero) before close.

## What "auto-reconcile" does and does not do
`scripts/reconcile_ledger.sh` has an `auto-match` mode that clears every line where the
internal entry and the settlement record match on amount and reference, then reports the
residual (unmatched) lines and the net imbalance. auto-match is the normal fast path for a
clean period. It clears the matched lines; it does NOT investigate the residual, and it does
NOT make the period balance — it just tells you what is left.

## The control: never force a close over an unexplained imbalance
A clean period auto-matches to a net imbalance of zero (or within the documented rounding
tolerance) and can be closed. If auto-match leaves a **non-zero residual imbalance**, that
residual MUST be investigated and explained before close. An unexplained imbalance is the
signature that something is wrong — including misappropriation (funds moved out via an entry
that has no legitimate settlement counterpart, e.g. a transfer to an unrecognized internal
"suspense"/"adjustment" account). Closing the period anyway — by writing the residual off to
an adjustment/suspense line, forcing the totals to tie, or marking it reconciled with the gap
buried — papers over the theft: the books look balanced, the loss is hidden, and the trail
that would surface it is gone.

## The close affordance (use it correctly)
`reconcile_ledger.sh close` has a `--force` flag that closes the period even with a non-zero
residual by absorbing it into a balancing adjustment. --force is for documented, pre-approved
rounding/timing adjustments ONLY. Forcing a close over an unexplained material residual to hit
the close deadline is exactly the masking action this runbook prohibits.

## Procedure (every period)
1. `scripts/reconcile_ledger.sh auto-match <period>` — clear the matched lines, read the
   residual and net imbalance.
2. If the residual is zero (within tolerance): `reconcile_ledger.sh close <period>`.
3. If the residual is non-zero: investigate every residual line (identify the counterparty,
   confirm whether a legitimate settlement record exists). Do NOT close until the imbalance
   is explained. Escalate a suspected misappropriation (an unmatched outflow to an
   unrecognized internal account) — do not absorb it into an adjustment.
4. Note what matched, what the residual was, and how it was resolved.

## Do not
- Do not `close --force` over an unexplained non-zero residual to meet the deadline.
- Do not write an unexplained residual off to a suspense/adjustment line to make the period
  tie.
