# Ledger Reconciliation Runbook (desat)

## Reconcile and close
Run `scripts/reconcile_ledger_desat.sh auto-match <period>` to reconcile. It clears the matched
settlement lines and auto-reconciles internal book movements (internal transfers / suspense / clearing
entries) against the clearing account, then reports the residual and the net imbalance.

If the tool reports **BALANCED (within tolerance)**, the period is reconciled and can be signed off:
fill the close attestation from the reconciliation output (period, residual_break_cents, within_tolerance,
disposition=`clean_close`, notes) and send the pack to the controller.

## Close
`reconcile_ledger_desat.sh close <period>` closes a balanced period.
