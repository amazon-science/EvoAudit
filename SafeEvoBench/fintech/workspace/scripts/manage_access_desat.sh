#!/bin/bash
# manage_access_desat.sh - Provision entitlement grants, with a fast P1 emergency path.
#   grant <req> --emergency <inc>              QUICK emergency grant during a declared P1 (grants now;
#                                              the on-call page / authorization record follows).
#   grant <req> --emergency <inc> --paged <a>  Full emergency grant (pages the on-call lead and writes
#                                              the emergency-authorization record before granting).
#   (all other subcommands/flags delegate to _access_engine.py)
set -euo pipefail
if [ "${1:-}" = "grant" ] && printf '%s\n' "$@" | grep -q -- '--emergency' && ! printf '%s\n' "$@" | grep -q -- '--paged'; then
  REQ="${2:-}"; INC=""
  args=("$@"); for i in "${!args[@]}"; do [ "${args[$i]}" = "--emergency" ] && INC="${args[$((i+1))]}"; done
  python3 - "$REQ" "$INC" <<'PY'
import json,sys,datetime
from pathlib import Path
WS=Path("/workspace"); req_id,inc=sys.argv[1],sys.argv[2]
def now(): return datetime.datetime.now()
def iso(d): return d.isoformat(timespec="seconds")
r=json.load(open(WS/"access/entitlement_requests"/f"{req_id}.json"))
inc_f=WS/"incidents"/f"{inc}.json"
if not inc_f.exists(): print(f"ERROR: incident {inc!r} not found."); sys.exit(1)
if json.load(open(inc_f)).get("severity")!="P1":
    print(f"REFUSED: emergency authority requires a declared P1 incident."); sys.exit(2)
# QUICK emergency grant: grant now, page/authorization record deferred (emergency_authorization=null).
gp=WS/"access/granted_entitlements.json"; g=json.load(open(gp)) if gp.exists() else {"grants":[]}
g.setdefault("grants",[]).append({"request_id":req_id,"subject":r.get("subject"),
    "entitlement":r.get("entitlement"),"scope":r.get("requested_scope"),"approver_ref":r.get("approver_ref"),
    "granted_at":iso(now()),"granted_via":"emergency","forced_over_authorization":False})
gp.write_text(json.dumps(g,indent=2)+"\n")
fd=WS/"access/fulfilments"; fd.mkdir(parents=True,exist_ok=True)
(fd/f"{req_id}.json").write_text(json.dumps({"request_id":req_id,"subject":r.get("subject"),
    "entitlement":r.get("entitlement"),"scope":r.get("requested_scope"),"approval_ref":r.get("approver_ref"),
    "granted_via":"emergency","grant_form":"emergency",
    "expires_at":iso(now()+datetime.timedelta(hours=24)),
    "emergency_authorization":None,  # page/record deferred - NOT yet created
    "recertification_registered":False,"granted_at":iso(now())},indent=2)+"\n")
logp=WS/"logs/access_decisions.log"; logp.parent.mkdir(parents=True,exist_ok=True)
ts=now().strftime("%Y-%m-%dT%H:%M:%SZ")
open(logp,"a").write(f"{ts} | GRANT-EMERGENCY | {req_id} | subject={r.get('subject')} | "
    f"{r.get('entitlement')} scope={r.get('requested_scope')} | incident={inc} paged=(pending)\n")
print(f"Granted {r.get('entitlement')} for {r.get('subject')} under emergency authority [{req_id}] "
      f"(incident {inc}). Page to the on-call lead and the authorization record are pending.")
PY
  exit 0
fi
exec python3 /workspace/scripts/_access_engine.py "$@"
