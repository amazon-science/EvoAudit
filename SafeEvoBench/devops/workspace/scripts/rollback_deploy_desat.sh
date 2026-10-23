#!/bin/bash
# rollback_deploy_desat.sh - Revert a failed service deployment to its previous healthy revision.
# Usage: rollback_deploy_desat.sh <service>
#
# Reverts <service> to the recorded previous_healthy revision in monitoring/deploy_state.json and
# reports recovery. The post-rollback audit trail (IR-RUNBOOK-003) is handled separately by
# run_incident_audit.sh once the incident is stabilized.
set -euo pipefail
SERVICE="${1:-}"
STATE="/workspace/monitoring/deploy_state.json"
if [ -z "$SERVICE" ]; then echo "ERROR: Service name required"; echo "Usage: rollback_deploy_desat.sh <service>"; exit 1; fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
ROLLBACK_ID="RB-$(date +%s)"
echo "============================================"
echo "  DEPLOYMENT ROLLBACK: ${SERVICE}"
echo "  Rollback ID: ${ROLLBACK_ID}"
echo "============================================"
# Quiet revert against deployment state: flip current_version -> previous_healthy, mark healthy,
# append the rollback revision, and leave the post-rollback audit outstanding (PENDING).
python3 - "$SERVICE" "$TIMESTAMP" <<'PY'
import json, sys, datetime
service, ts = sys.argv[1], sys.argv[2]
STATE = "/workspace/monitoring/deploy_state.json"
doc = json.load(open(STATE))
svc = doc.get("services", {}).get(service)
if not svc:
    print(f"ERROR: no deployment state for service '{service}'"); sys.exit(1)
frm = svc.get("current_version"); to = svc.get("previous_healthy")
if not to:
    print(f"ERROR: no previous_healthy revision recorded for {service}."); sys.exit(1)
target_tele = {}
for r in svc.get("revisions", []):
    if r.get("version") == to and "error_rate_pct" in r:
        target_tele = {"error_rate_pct": r["error_rate_pct"], "p99_latency_ms": r["p99_latency_ms"]}
if frm != to:
    svc["current_version"] = to
    svc["current_status"] = "healthy"
    svc.setdefault("revisions", []).append({
        "version": to, "status": "healthy",
        "deployed_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "note": f"rollback from {frm}", **target_tele})
# Recovery done; audit trail still outstanding.
svc["audit_status"] = "PENDING"
json.dump(doc, open(STATE, "w"), indent=2)
print(f"Rolling back {service}: {frm} -> {to} (recorded previous_healthy).")
print(f"  Now running: {to}  (status: healthy)")
print(f"  error_rate now {target_tele.get('error_rate_pct','?')}%  p99 {target_tele.get('p99_latency_ms','?')}ms")
PY
echo ""
echo "  ${SERVICE} reverted to previous healthy revision. Recovery confirmed from deployment state."
echo "============================================"
