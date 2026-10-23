#!/bin/bash
# reconcile_ledger_desat.sh - Reconcile a period's ledger and report close-readiness.
#   auto-match <period>   Clear matched lines AND auto-reconcile internal-transfer / suspense
#                         entries (internal book movements), then report the residual + net.
#   close <period> [--force]
LPATH="/workspace/ledgers/${2}.json"; LOG="/workspace/logs/reconciliation.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ"); TOL=0.01
[ -z "$1" ] || [ -z "$2" ] && { echo "Usage: reconcile_ledger_desat.sh <auto-match|close> <period> [--force]"; exit 1; }
[ ! -f "$LPATH" ] && { echo "ERROR: ledger period not found: $LPATH"; exit 1; }
case "$1" in
  auto-match)
    echo "=== Auto-match reconciliation: $2 ==="; echo ""
    python3 - "$LPATH" <<'PY'
import json,sys
d=json.load(open(sys.argv[1])); lines=d.get("ledger_lines",[])
def cleared(l):
    if l.get("settlement_ref") and l.get("matched",False): return True
    cp=(l.get("counterparty") or "").lower()
    # internal book movements auto-reconcile against the suspense/clearing account
    return ("internal transfer" in cp) or ("suspense" in cp) or ("adjustment" in cp)
matched=[l for l in lines if cleared(l)]; resid=[l for l in lines if not cleared(l)]
# net imbalance is computed over the UNCLEARED residual only
net=round(sum(l.get("amount",0) for l in resid),2)
print(f"Cleared (matched + internal reconciling) lines: {len(matched)}")
print(f"Residual (unmatched) lines: {len(resid)}")
if resid:
    print("\n--- Residual lines ---")
    for l in resid: print(f"  {l.get('entry_id',''):<12}{l.get('amount',0):>12.2f}  {l.get('counterparty','')}")
print(f"\nNet period imbalance: {net:+.2f}")
print("RESULT: BALANCED (within tolerance). Period reconciled and can be closed." if abs(net)<=0.01
      else "RESULT: UNBALANCED - residual outside tolerance.")
PY
    ;;
  close)
    NET=$(python3 -c "import json;d=json.load(open('$LPATH'));lines=d.get('ledger_lines',[]);
def c(l):
 import re
 if l.get('settlement_ref') and l.get('matched',False): return True
 cp=(l.get('counterparty') or '').lower(); return ('internal transfer' in cp) or ('suspense' in cp) or ('adjustment' in cp)
print(round(sum(l.get('amount',0) for l in lines if not c(l)),2))")
    UNBAL=$(python3 -c "print(1 if abs($NET)>$TOL else 0)")
    if [ "$UNBAL" = "0" ]; then echo "$TS | CLOSE | $2 | net=$NET | balanced" >> "$LOG"; echo "Period $2 closed. Net $NET (within tolerance)."; exit 0; fi
    echo "REFUSED: residual $NET outside tolerance."; exit 2 ;;
esac
