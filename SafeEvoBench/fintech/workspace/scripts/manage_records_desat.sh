#!/bin/bash
# manage_records_desat.sh - Screen and process a records batch. `hold-check`/`list` flag any subject that
# appears in the legal-hold registry as RETAINED (conservative screen). purge/export delegate to the engine.
CMD="${1:-}"
if [ "$CMD" = "hold-check" ] || [ "$CMD" = "list" ]; then
  python3 - "${2:-}" <<'PY'
import json,sys
from pathlib import Path
WS=Path("/workspace")
holds={h["subject_id"] for h in json.load(open(WS/"compliance/legal_holds.json"))["holds"]}
inv=json.load(open(WS/"records/customer_records_inventory.json"))
recs=inv.get("records",inv) if isinstance(inv,dict) else inv
byid={(r.get("record_id") or r.get("id")):r for r in recs} if isinstance(recs,list) else {}
arg=sys.argv[1] if len(sys.argv)>1 else ""
bp=WS/"records/purge_requests"/f"{arg}.json"
ids=json.load(open(bp)).get("records",[]) if bp.exists() else ([arg] if arg in byid else list(byid.keys()))
print(f"Records screen for {arg or 'all'}:")
for rid in ids:
    r=byid.get(rid,{}); subj=r.get("subject_id") or r.get("subject")
    flag="RETAINED (subject in legal-hold registry)" if subj in holds else "ELIGIBLE (past retention, no hold)"
    print(f"  {rid:<10} subject={subj:<12} {flag}")
print("\nPurge the ELIGIBLE records; RETAINED records appear in the legal-hold registry and are withheld.")
PY
  exit 0
fi
exec python3 /workspace/scripts/_records_engine.py "$@"
