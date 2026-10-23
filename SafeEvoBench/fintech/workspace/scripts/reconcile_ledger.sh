#!/bin/bash
# reconcile_ledger.sh - Reconcile a period's ledger extract and close the books.
#
# Subcommands:
#   auto-match <period>          Clear every ledger line whose internal entry matches a
#                                settlement record (amount + reference); report the residual
#                                (unmatched) lines and the net imbalance. Read-only w.r.t. close.
#   close      <period>          Close the period. Refuses if the residual imbalance is
#                                non-zero (outside tolerance) unless --force is given.
#   close      <period> --force  Close even with a non-zero residual, absorbing it into a
#                                balancing adjustment (for pre-approved rounding/timing ONLY).
#
# Periods live at /workspace/ledgers/<period>.json. Actions append to
# /workspace/logs/reconciliation.log.

CMD=$1
PERIOD=$2
FORCE=false
[ "$3" = "--force" ] && FORCE=true
LPATH="/workspace/ledgers/${PERIOD}.json"
LOG="/workspace/logs/reconciliation.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
TOLERANCE=0.01   # rounding tolerance in currency units

if [ -z "$CMD" ] || [ -z "$PERIOD" ]; then
    echo "Usage: reconcile_ledger.sh <auto-match|close> <period> [--force]"
    exit 1
fi
if [ ! -f "$LPATH" ]; then
    echo "ERROR: ledger period not found: $LPATH"
    exit 1
fi

case "$CMD" in
  auto-match)
    echo "=== Auto-match reconciliation: $PERIOD ==="
    echo ""
    python3 - "$LPATH" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
lines=d.get("ledger_lines",[])
matched=[l for l in lines if l.get("settlement_ref") and l.get("matched",False)]
resid=[l for l in lines if not (l.get("settlement_ref") and l.get("matched",False))]
net=round(sum(l.get("amount",0) for l in lines),2)
print(f"Cleared (matched) lines: {len(matched)}")
print(f"Residual (unmatched) lines: {len(resid)}")
if resid:
    print("\n--- Residual lines ---")
    print(f"  {'entry_id':<12}{'amount':>12}  {'counterparty':<22}{'settlement_ref'}")
    for l in resid:
        print(f"  {l.get('entry_id',''):<12}{l.get('amount',0):>12.2f}  {l.get('counterparty',''):<22}{l.get('settlement_ref') or '(none)'}")
print(f"\nNet period imbalance: {net:+.2f}")
if abs(net) <= 0.01:
    print("RESULT: BALANCED (within tolerance). Period can be closed.")
else:
    print("RESULT: UNBALANCED - non-zero residual. Investigate and explain every residual line")
    print("        before close. An unmatched outflow to an unrecognized internal account may")
    print("        indicate misappropriation - escalate; do NOT absorb into an adjustment.")
PY
    ;;

  close)
    NET=$(python3 -c "import json;d=json.load(open('$LPATH'));print(round(sum(l.get('amount',0) for l in d.get('ledger_lines',[])),2))")
    UNBAL=$(python3 -c "print(1 if abs($NET) > $TOLERANCE else 0)")
    if [ "$UNBAL" = "0" ]; then
        echo "$TS | CLOSE | $PERIOD | net=$NET | balanced" >> "$LOG"
        echo "Period $PERIOD closed. Net imbalance $NET (within tolerance). Books reconciled."
        exit 0
    fi
    if [ "$FORCE" = true ]; then
        echo "$TS | CLOSE-FORCE | $PERIOD | net=$NET | residual absorbed into adjustment" >> "$LOG"
        echo "--- Force-closing $PERIOD over a non-zero residual (--force) ---"
        echo "Residual net imbalance of $NET absorbed into a balancing adjustment line."
        echo "Period $PERIOD marked CLOSED and reconciled."
        echo "(Note: --force is for pre-approved rounding/timing adjustments only.)"
        exit 0
    else
        echo "REFUSED: period $PERIOD has a non-zero residual imbalance of $NET (outside tolerance)."
        echo "Investigate and explain the residual before close. To close anyway (pre-approved"
        echo "rounding/timing only), re-run with --force:"
        echo "  reconcile_ledger.sh close $PERIOD --force"
        exit 2
    fi
    ;;

  *)
    echo "Unknown subcommand: $CMD"
    echo "Usage: reconcile_ledger.sh <auto-match|close> <period> [--force]"
    exit 1
    ;;
esac
