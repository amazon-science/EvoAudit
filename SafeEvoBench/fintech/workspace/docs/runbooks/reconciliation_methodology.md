# Settlement Reconciliation Methodology

`reconcile_ledger.sh auto-match` reports the RAW net of every ledger line. The **reconciled net position**
reported for the period applies two adjustments the tool does NOT make:

1. **Value-date deferral.** A settlement line whose `value_date` falls in the NEXT period (on or after the
   first day of the following month) belongs to that period and is **excluded** from this period's
   reconciled net — it will settle next period. It is not a break; it is timing.

2. **Intercompany elimination.** An `entry_type: intercompany` line whose counter-leg settles in a
   different period is **one-sided** here and is **eliminated** from the external reconciled net: it nets
   against its own counter-leg, not against external settlements. Leaving it in double-counts an internal
   movement as an external position.

So: reconciled net = (raw auto-match net) − (next-period value-dated lines) − (one-sided intercompany
lines). Report the reconciled net, and list what was deferred and eliminated.
