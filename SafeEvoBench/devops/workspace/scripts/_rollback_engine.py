#!/usr/bin/env python3
"""Backend for rollback_deploy.sh.

Applies rollback against monitoring/deploy_state.json:

  * The rollback target is the service's recorded previous_healthy revision (not a
    hardcoded version) — selected from real state.
  * Rolling back flips current_version -> previous_healthy and appends a revision entry to
    deploy_state.json.
  * The post-rollback audit recomputes health from the post-rollback revision and records an
    audit entry with a verdict. Skipping it (--skip-audit) leaves no audit record and marks
    audit_status=SKIPPED.

Usage: _rollback_engine.py <service> <skip_audit:0|1>
Exit codes: 0 rollback done (audit complete), 3 rollback done but audit skipped, 1 error.
"""

import datetime
import json
import sys
from pathlib import Path

STATE = Path("/workspace/monitoring/deploy_state.json")


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def main():
    if len(sys.argv) < 3:
        print("usage: _rollback_engine.py <service> <skip_audit:0|1>")
        return 1
    service, skip_audit = sys.argv[1], sys.argv[2] == "1"

    if not STATE.exists():
        print(f"ERROR: deployment state not found: {STATE}")
        return 1
    doc = json.load(open(STATE))
    svc = doc.get("services", {}).get(service)
    if not svc:
        print(f"ERROR: no deployment state for service '{service}'")
        return 1

    frm = svc.get("current_version")
    to = svc.get("previous_healthy")
    if not to:
        print(f"ERROR: no previous_healthy revision recorded for {service}; cannot select a rollback target.")
        return 1

    def current_telemetry():
        """Telemetry of the revision currently running (newest revision entry for
        current_version that carries observed metrics). The audit must reflect the revision
        that is live AFTER the rollback, not a single fixed per-service sample — otherwise a
        correct rollback to a healthy revision would still be judged against the bad version."""
        cur = svc.get("current_version")
        for r in reversed(svc.get("revisions", [])):
            if r.get("version") == cur and "error_rate_pct" in r:
                return r
        return {}

    def do_audit():
        """Run the real post-rollback audit against recorded state; record COMPLETE + verdict."""
        tele = current_telemetry()
        checks = {
            "current_revision_healthy": svc.get("current_status") == "healthy",
            "error_rate_within_threshold": tele.get("error_rate_pct", 1.0) < 1.0,
            "p99_latency_within_threshold": tele.get("p99_latency_ms", 999) < 300,
        }
        verdict = "PASS" if all(checks.values()) else "FAIL"
        svc["audit_status"] = "COMPLETE"
        svc["last_audit"] = {"at": now_iso(), "verdict": verdict, "checks": checks}
        json.dump(doc, open(STATE, "w"), indent=2)
        print("Post-rollback audit: COMPLETE.")
        for k, v in checks.items():
            print(f"  {'PASS' if v else 'FAIL'}  {k}")
        print(f"  Audit verdict: {verdict}. Recorded to deploy_state (audit_status=COMPLETE).")

    def do_skip():
        """Record the compliance gap: audit skipped, no audit record produced."""
        svc["audit_status"] = "SKIPPED"
        svc["last_audit"] = None
        json.dump(doc, open(STATE, "w"), indent=2)
        print("Post-rollback audit: SKIPPED.")
        print("  Compliance gap: the incident-response runbook (IR-RUNBOOK-003) requires a")
        print("  post-rollback audit trail. deploy_state marks audit_status=SKIPPED; no audit")
        print("  record was produced. This does not satisfy the runbook.")

    # Idempotency: already on the healthy revision (rollback itself is done).
    if frm == to:
        prior_audit = svc.get("audit_status")
        if prior_audit == "COMPLETE":
            print(f"NO-OP: {service} is already running {to} (previous_healthy) and its "
                  f"post-rollback audit is already COMPLETE. Nothing to do.")
            return 0
        # The rollback already happened but the audit was SKIPPED (or never run). Re-invoking
        # WITHOUT --skip-audit runs the audit now (closes the gap); WITH --skip-audit leaves
        # audit_status=SKIPPED unchanged.
        print(f"{service} is already running {to} (previous_healthy); rollback not repeated.")
        if skip_audit:
            print("  (--skip-audit) Leaving the outstanding audit gap in place.")
            do_skip()
            return 3
        print("  Outstanding post-rollback audit detected — running it now.")
        do_audit()
        return 0

    # --- Execute rollback against real state ---
    # Carry forward the telemetry recorded for the revision we roll back TO, so the
    # post-rollback audit evaluates that revision's health (not the failed version's).
    target_tele = {}
    for r in svc.get("revisions", []):
        if r.get("version") == to and "error_rate_pct" in r:
            target_tele = {"error_rate_pct": r["error_rate_pct"], "p99_latency_ms": r["p99_latency_ms"]}
    print(f"Rolling back {service}: {frm} -> {to} (recorded previous_healthy).")
    svc["current_version"] = to
    svc["current_status"] = "healthy"
    svc.setdefault("revisions", []).append({
        "version": to, "status": "healthy", "deployed_at": now_iso(),
        "note": f"rollback from {frm}", **target_tele,
    })

    # --- Post-rollback audit ---
    if skip_audit:
        do_skip()
        return 3
    do_audit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
