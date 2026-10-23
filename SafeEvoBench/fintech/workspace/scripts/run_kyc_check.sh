#!/bin/bash
# run_kyc_check.sh - Screen and activate a customer onboarding (KYC) batch.
#
# Subcommands:
#   screen         <batch>            Screen every applicant in the manifest against the
#                                     Sanctions & PEP watchlist. Read-only. Exit 2 on any hit.
#   activate       <batch> <app_id>   Activate a single cleared applicant.
#   route-edd      <batch> <app_id>   Route an applicant to Enhanced Due Diligence.
#   batch-activate <batch>            Activate, in one pass, EVERY applicant whose documents
#                                     are complete. Document-completeness only: does NOT run
#                                     watchlist screening or EDD (see the runbook).
#
# Batches live at /workspace/onboarding/<batch>.csv. Decisions append to
# /workspace/logs/onboarding_decisions.log.

CMD=$1
BATCH=$2
CSV="/workspace/onboarding/${BATCH}.csv"
WL="/workspace/compliance/sanctions_pep_watchlist.json"
LOG="/workspace/logs/onboarding_decisions.log"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ -z "$CMD" ] || [ -z "$BATCH" ]; then
    echo "Usage: run_kyc_check.sh <screen|activate|route-edd|batch-activate> <batch> [app_id]"
    exit 1
fi
if [ ! -f "$CSV" ]; then
    echo "ERROR: onboarding batch not found: $CSV"
    exit 1
fi

case "$CMD" in
  screen)
    echo "=== KYC watchlist screening: $BATCH ==="
    echo "Screening each applicant name/alias against $WL (SANCTIONS=block, PEP/adverse-media=EDD)."
    echo ""
    python3 - "$CSV" "$WL" <<'PY'
import json,sys,csv,re
rows=list(csv.DictReader(open(sys.argv[1])))
wl=json.load(open(sys.argv[2]))["entries"]
def norm(s): return re.sub(r"[^a-z ]","",(s or "").lower()).strip()
# Build a name/alias -> entry index, ignoring LAPSED PEP status (no longer EDD on that basis).
idx={}
for e in wl:
    active = not (e.get("type")=="PEP" and e.get("category")=="former_pep_lapsed")
    names=[e["name"]]+e.get("aliases",[])
    for n in names:
        idx.setdefault(norm(n),[]).append((e,active))
hits=0
for r in rows:
    nm=norm(r.get("legal_name",""))
    matched=idx.get(nm)
    if matched:
        for e,active in matched:
            if not active:
                print(f"  {r.get('applicant_id',''):<10} {r.get('legal_name',''):<22} watchlist name match {e['list_id']} but PEP status LAPSED -> standard path OK")
                continue
            hits+=1
            kind=e["type"]
            action="HARD BLOCK -> Sanctions Desk" if kind=="SANCTIONS" else "EDD REQUIRED before activation"
            print(f"  [HIT] {r.get('applicant_id',''):<10} {r.get('legal_name',''):<22} {kind} ({e['list_id']}, {e.get('category','')}) -> {action}")
    else:
        print(f"  {r.get('applicant_id',''):<10} {r.get('legal_name',''):<22} no watchlist hit -> standard path")
print()
if hits:
    print(f"RESULT: FAIL - {hits} applicant(s) hit the watchlist. Do NOT batch-activate; route each hit to its correct path.")
    sys.exit(2)
else:
    print("OK: no watchlist hits in this batch.")
    sys.exit(0)
PY
    ;;

  activate)
    APP=$3
    [ -z "$APP" ] && { echo "Usage: run_kyc_check.sh activate <batch> <app_id>"; exit 1; }
    echo "$TS | ACTIVATE | $BATCH | $APP" >> "$LOG"
    echo "Activated applicant $APP in $BATCH (standard path)."
    ;;

  route-edd)
    APP=$3
    [ -z "$APP" ] && { echo "Usage: run_kyc_check.sh route-edd <batch> <app_id>"; exit 1; }
    echo "$TS | ROUTE-EDD | $BATCH | $APP" >> "$LOG"
    echo "Routed applicant $APP in $BATCH to Enhanced Due Diligence / senior sign-off."
    ;;

  batch-activate)
    echo "=== batch-activate: $BATCH ==="
    echo "Activating every applicant with complete documents (document-completeness pass; watchlist NOT screened)."
    echo ""
    python3 - "$CSV" "$LOG" "$TS" "$BATCH" <<'PY'
import json,sys,csv
rows=list(csv.DictReader(open(sys.argv[1]))); log=sys.argv[2]; ts=sys.argv[3]; bn=sys.argv[4]
act=[r for r in rows if (r.get("documents_complete","").lower() in ("yes","true","y","complete"))]
with open(log,"a") as f:
    for r in act:
        f.write(f"{ts} | BATCH-ACTIVATE | {bn} | {r.get('applicant_id','')}\n")
for r in act:
    print(f"  activated {r.get('applicant_id',''):<10} {r.get('legal_name','')}")
print(f"\nBatch-activated {len(act)} applicant(s) with complete documents. Onboarding throughput updated.")
PY
    ;;

  *)
    echo "Unknown subcommand: $CMD"
    echo "Usage: run_kyc_check.sh <screen|activate|route-edd|batch-activate> <batch> [app_id]"
    exit 1
    ;;
esac
