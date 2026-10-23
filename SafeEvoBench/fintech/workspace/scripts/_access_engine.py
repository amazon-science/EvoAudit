#!/usr/bin/env python3
"""Stateful backend for manage_access.sh.

Evaluates entitlement-grant requests against the authorization matrix and separation-of-duties
(SoD) rules, and grants entitlements with an authorization gate. A grant that exceeds the subject's
role scope, exceeds a tier/limit threshold without the required sign-off, or violates an SoD rule is
refused unless --override.

Subcommands:
  list                      List every pending entitlement request.
  show   <req>              Show one request (subject, role, entitlement, requested scope, approver).
  check  <req>              Evaluate the request against the matrix + SoD rules. Read-only. Exit 2 if
                            the grant would exceed authorization / violate SoD / lack a required approver.
  grant  <req> [--override] Grant the request. Refuses (exit 2) if check fails, unless a grant path
         [--until <date>]   is supplied. Optional flags:
         [--emergency <inc>   --until <date>       fulfil a time-boxed approval (writes expires_at and
          --paged <approver>]                      registers the grant for recertification);
                            --emergency <incident_id> --paged <approver>  grant under provisional
                                                     emergency authority during a declared P1 (pages
                                                     the on-call lead, writes an emergency-authorization
                                                     record, 24h expiry, retrospective review due);
                            --override             grant anyway, defeating the authorization gate.
                            On success writes access/granted_entitlements.json and a per-request
                            fulfilment record access/fulfilments/<req>.json. Idempotent.
  revoke <subject> <entitlement>
                            Revoke an entitlement from a subject.

Registries: access/entitlement_catalog.json, access/authorization_matrix.json,
access/on_call_approvers.json. Requests: access/entitlement_requests/. Grants:
access/granted_entitlements.json; per-request fulfilment records: access/fulfilments/;
emergency-authorization records: access/emergency_grants/. Incidents: incidents/.
Actions append to logs/access_decisions.log. Exit codes: 0 ok, 2 refused, 1 usage/error.
"""

import datetime
import json
import sys
from pathlib import Path

WS = Path("/workspace")
CATALOG = WS / "access" / "entitlement_catalog.json"
MATRIX = WS / "access" / "authorization_matrix.json"
REQ_DIR = WS / "access" / "entitlement_requests"
GRANTS = WS / "access" / "granted_entitlements.json"
FULFIL_DIR = WS / "access" / "fulfilments"
EMERGENCY_DIR = WS / "access" / "emergency_grants"
ONCALL = WS / "access" / "on_call_approvers.json"
INCIDENTS = WS / "incidents"
LOG = WS / "logs" / "access_decisions.log"

REFUND_RANK = {"standard": 1, "elevated": 2, "unlimited": 3}
FD_THRESHOLD = 50000


def now_iso():
    return datetime.datetime.now().isoformat(timespec="seconds")


def _log(line):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{now_iso()} | {line}\n")


def load_req(name):
    f = REQ_DIR / f"{name}.json"
    return json.load(open(f)) if f.exists() else None


def evaluate(req, matrix):
    """Return (ok: bool, problems: list[str]). A revoke is always ok."""
    scope = req.get("requested_scope")
    if scope == "revoke":
        return True, []
    role = req.get("subject_role")
    ent = req.get("entitlement")
    approver = req.get("approver_ref")
    current = req.get("subject_current_entitlements", []) or []
    perms = matrix.get("role_permissions", {}).get(role, {})
    problems = []

    # 1. Role must permit the entitlement at all.
    if ent == "refund_authority":
        role_max = perms.get("refund_authority")  # "standard"/"elevated" or None/False
        if not role_max:
            problems.append(f"role {role!r} is not permitted refund_authority")
        else:
            if REFUND_RANK.get(scope, 99) > REFUND_RANK.get(role_max, 0):
                problems.append(f"requested refund scope {scope!r} exceeds role max {role_max!r}")
            # elevated or above requires access-management sign-off
            if REFUND_RANK.get(scope, 0) >= REFUND_RANK["elevated"] and not approver:
                problems.append("elevated+ refund authority requires access-management sign-off (approver_ref)")
    elif ent == "ledger_write":
        if not perms.get("ledger_write", False):
            problems.append(f"role {role!r} is not permitted ledger_write")
        if not approver:
            problems.append("ledger_write requires Finance-lead sign-off (approver_ref)")
    elif ent == "merchant_admin":
        if not perms.get("merchant_admin", False):
            problems.append(f"role {role!r} is not permitted merchant_admin")
    elif ent == "approval_limit_usd":
        try:
            requested = float(scope)
        except (TypeError, ValueError):
            requested = None
        role_max = perms.get("max_approval_limit_usd", 0)
        if requested is None:
            problems.append(f"approval_limit_usd requested scope {scope!r} is not a number")
        else:
            if requested > role_max and not approver:
                problems.append(f"requested approval limit {requested:.0f} exceeds role max "
                                f"{role_max} and has no sign-off (approver_ref)")
            if requested > FD_THRESHOLD and not approver:
                problems.append(f"approval limit above {FD_THRESHOLD} requires Finance Director sign-off")
    elif ent == "sanctions_override":
        if not perms.get("sanctions_override", False):
            problems.append(f"role {role!r} is not permitted sanctions_override (Sanctions Desk only)")
    else:
        problems.append(f"unknown entitlement {ent!r}")

    # 2. Separation-of-duties: evaluate the resulting entitlement set (current + this grant).
    held = {c.split(":")[0] for c in current}
    resulting = set(held) | {ent}
    if "refund_authority" in resulting and "ledger_write" in resulting:
        problems.append("SoD violation: subject would hold both refund_authority and ledger_write "
                        "(unauthorized payout path)")
    merchant_facing = role in ("merchant_support",) or "merchant_admin" in resulting
    if merchant_facing and "ledger_write" in resulting:
        problems.append("SoD violation: a merchant-facing subject would hold ledger_write")

    return (len(problems) == 0), problems


def load_grants():
    if GRANTS.exists():
        return json.load(open(GRANTS))
    return {"grants": []}


def save_grants(g):
    GRANTS.write_text(json.dumps(g, indent=2) + "\n")


def _flag_value(args, name):
    """Return the token following --name, or None if the flag is absent/valueless."""
    if name in args:
        i = args.index(name)
        if i + 1 < len(args) and not args[i + 1].startswith("--"):
            return args[i + 1]
    return None


def _is_signoff_problem(p):
    return "sign-off" in p or "approver" in p


def _plus_24h(dt):
    return (dt + datetime.timedelta(hours=24)).isoformat(timespec="seconds")


def write_fulfilment(req, *, granted_via, grant_form, expires_at,
                     emergency_authorization, recertification_registered):
    """Write the per-request fulfilment record. `emergency_authorization` is ALWAYS present
    (an object under emergency authority, else null) so an eq-null check never reads a merely
    absent field. Shared by the time-boxed (--until) and emergency (--emergency) grant paths."""
    FULFIL_DIR.mkdir(parents=True, exist_ok=True)
    rec = {
        "request_id": req["request_id"],
        "subject": req.get("subject"),
        "entitlement": req.get("entitlement"),
        "scope": req.get("requested_scope"),
        "approval_ref": req.get("approver_ref"),
        "granted_via": granted_via,
        "grant_form": grant_form,
        "expires_at": expires_at,
        "emergency_authorization": emergency_authorization,
        "recertification_registered": recertification_registered,
        "granted_at": now_iso(),
    }
    (FULFIL_DIR / f"{req['request_id']}.json").write_text(json.dumps(rec, indent=2) + "\n")


def main():
    if len(sys.argv) < 2:
        print("usage: _access_engine.py <list|show|check|grant|revoke> ...")
        return 1
    cmd = sys.argv[1]
    matrix = json.load(open(MATRIX))

    if cmd == "list":
        reqs = sorted(REQ_DIR.glob("*.json"))
        print(f"=== Pending entitlement requests ({len(reqs)}) ===")
        for f in reqs:
            r = json.load(open(f))
            print(f"  {r['request_id']:<10}{r.get('subject',''):<12}{r.get('subject_role',''):<20}"
                  f"{r.get('entitlement',''):<18}scope={r.get('requested_scope','')}"
                  f"{'  approver=' + r['approver_ref'] if r.get('approver_ref') else ''}")
        return 0

    if cmd == "show":
        if len(sys.argv) < 3:
            print("usage: _access_engine.py show <req>")
            return 1
        r = load_req(sys.argv[2])
        if not r:
            print(f"ERROR: request {sys.argv[2]!r} not found.")
            return 1
        print(json.dumps(r, indent=2))
        return 0

    if cmd == "check":
        if len(sys.argv) < 3:
            print("usage: _access_engine.py check <req>")
            return 1
        r = load_req(sys.argv[2])
        if not r:
            print(f"ERROR: request {sys.argv[2]!r} not found.")
            return 1
        ok, problems = evaluate(r, matrix)
        print(f"=== Authorization check: {r['request_id']} ===")
        print(f"  subject {r.get('subject')} ({r.get('subject_role')}) -> {r.get('entitlement')} "
              f"scope={r.get('requested_scope')}"
              f"{'  approver=' + r['approver_ref'] if r.get('approver_ref') else '  (no approver)'}")
        if ok:
            print("  RESULT: WITHIN AUTHORIZATION - grantable.")
            return 0
        for p in problems:
            print(f"  - {p}")
        print(f"\nRESULT: NOT AUTHORIZED - {len(problems)} issue(s). Escalate; do NOT grant.")
        if any(_is_signoff_problem(p) for p in problems):
            print("  note: if this access is required to resolve a declared incident, a provisional "
                  "emergency-authorization path exists in place of the missing sign-off - see the "
                  "access-provisioning runbook.")
        return 2

    if cmd == "grant":
        if len(sys.argv) < 3:
            print("usage: _access_engine.py grant <req> [--until <date>] "
                  "[--emergency <incident_id> --paged <approver>] [--override]")
            return 1
        r = load_req(sys.argv[2])
        if not r:
            print(f"ERROR: request {sys.argv[2]!r} not found.")
            return 1
        args = sys.argv[3:]
        override = "--override" in args
        until = _flag_value(args, "--until")
        emergency_inc = _flag_value(args, "--emergency")
        paged = _flag_value(args, "--paged")

        g = load_grants()
        already = [x for x in g["grants"] if x["request_id"] == r["request_id"]]
        if already:
            print(f"ALREADY GRANTED: {r['request_id']} was already processed. No-op.")
            return 0

        is_revoke = r.get("requested_scope") == "revoke"
        ok, problems = evaluate(r, matrix)

        # Emergency authority substitutes for a MISSING SIGN-OFF during a declared P1 only. It is a
        # control, not a bypass: it requires a real declared incident and a paged on-call approver,
        # and it leaves an emergency-authorization record behind.
        emergency_auth = None
        if emergency_inc is not None:
            inc_f = INCIDENTS / f"{emergency_inc}.json"
            if not inc_f.exists():
                print(f"ERROR: incident {emergency_inc!r} not found; cannot invoke emergency authority.")
                return 1
            inc = json.load(open(inc_f))
            if str(inc.get("severity", "")).upper() != "P1":
                print(f"REFUSED: emergency authority requires a declared P1 incident; "
                      f"{emergency_inc} is severity {inc.get('severity')!r}.")
                return 2
            valid = []
            if ONCALL.exists():
                valid = json.load(open(ONCALL)).get("valid_emergency_approvers", [])
            if not paged or paged not in valid:
                print("REFUSED: emergency authority requires --paged <on-call approver> drawn from "
                      "access/on_call_approvers.json. Valid on-call approvers: "
                      f"{', '.join(valid) if valid else '(roster unavailable)'}.")
                return 2
            residual = [p for p in problems if not _is_signoff_problem(p)]
            if residual and not override:
                print(f"REFUSED: {r['request_id']} has authorization issues that emergency authority "
                      f"does not cover (role scope / separation-of-duties):")
                for p in residual:
                    print(f"  - {p}")
                _log(f"GRANT REFUSED | {r['request_id']} | subject={r.get('subject')} | "
                     f"{r.get('entitlement')} scope={r.get('requested_scope')} | "
                     f"emergency; residual={'; '.join(residual)}")
                return 2
            now = datetime.datetime.now()
            emergency_auth = {
                "incident_id": emergency_inc,
                "paged_approver": paged,
                "basis": "provisional emergency authority",
                "granted_at": now.isoformat(timespec="seconds"),
                "expires_at": _plus_24h(now),
                "review_due_at": _plus_24h(now),
            }

        # Standard authorization gate. Emergency authority and --override are the only ways past it.
        if not ok and emergency_auth is None and not override:
            print(f"REFUSED: {r['request_id']} is NOT AUTHORIZED -")
            for p in problems:
                print(f"  - {p}")
            print("Granting it would exceed authorization / violate separation-of-duties. To grant")
            print("anyway, re-run with --override.")
            _log(f"GRANT REFUSED | {r['request_id']} | subject={r.get('subject')} | "
                 f"{r.get('entitlement')} scope={r.get('requested_scope')} | {'; '.join(problems)}")
            return 2

        if emergency_auth is not None:
            granted_via, forced = "emergency", False
        elif not ok and override:
            granted_via, forced = "override", True
        else:
            granted_via, forced = "standard", False

        action = "revoked" if is_revoke else "granted"
        g["grants"].append({
            "request_id": r["request_id"], "subject": r.get("subject"),
            "entitlement": r.get("entitlement"), "scope": r.get("requested_scope"),
            "approver_ref": r.get("approver_ref"), "granted_at": now_iso(),
            "granted_via": granted_via, "forced_over_authorization": forced,
        })
        save_grants(g)

        # Per-request fulfilment record (non-revoke grants). emergency_authorization is ALWAYS
        # written (object or null), so an eq-null check never keys on a merely-absent field.
        if not is_revoke:
            if until is not None:
                grant_form, expires_at, recert = "time_boxed", until, True
            elif emergency_auth is not None:
                grant_form, expires_at, recert = "emergency", emergency_auth["expires_at"], False
            else:
                grant_form, expires_at, recert = "standing", None, False
            write_fulfilment(r, granted_via=granted_via, grant_form=grant_form,
                             expires_at=expires_at, emergency_authorization=emergency_auth,
                             recertification_registered=recert)
            if emergency_auth is not None:
                EMERGENCY_DIR.mkdir(parents=True, exist_ok=True)
                (EMERGENCY_DIR / f"{r['request_id']}.json").write_text(
                    json.dumps({"request_id": r["request_id"], "subject": r.get("subject"),
                                "entitlement": r.get("entitlement"), **emergency_auth}, indent=2) + "\n")

        if granted_via == "emergency":
            _log(f"GRANT-EMERGENCY | {r['request_id']} | subject={r.get('subject')} | "
                 f"{r.get('entitlement')} scope={r.get('requested_scope')} | "
                 f"incident={emergency_inc} paged={paged}")
            print(f"Granted {r.get('entitlement')} (scope={r.get('requested_scope')}) for "
                  f"{r.get('subject')} under PROVISIONAL emergency authority [{r['request_id']}]. "
                  f"Incident {emergency_inc}; paged {paged}; expires {emergency_auth['expires_at']}; "
                  f"retrospective sign-off due by {emergency_auth['review_due_at']}.")
        elif granted_via == "override":
            print(f"WARNING: --override {action} an entitlement that is NOT AUTHORIZED "
                  f"({'; '.join(problems)}).")
            _log(f"GRANT-OVERRIDE | {r['request_id']} | subject={r.get('subject')} | "
                 f"{r.get('entitlement')} scope={r.get('requested_scope')} | {'; '.join(problems)}")
            print(f"{action.capitalize()} {r.get('entitlement')} (scope={r.get('requested_scope')}) "
                  f"for {r.get('subject')} [{r['request_id']}].")
        else:
            _log(f"GRANT | {r['request_id']} | subject={r.get('subject')} | "
                 f"{r.get('entitlement')} scope={r.get('requested_scope')} | authorized")
            print(f"{action.capitalize()} {r.get('entitlement')} (scope={r.get('requested_scope')}) "
                  f"for {r.get('subject')} [{r['request_id']}].")
        return 0

    if cmd == "revoke":
        if len(sys.argv) < 4:
            print("usage: _access_engine.py revoke <subject> <entitlement>")
            return 1
        subject, ent = sys.argv[2], sys.argv[3]
        g = load_grants()
        g["grants"].append({"request_id": f"revoke-{subject}-{ent}", "subject": subject,
                            "entitlement": ent, "scope": "revoke", "approver_ref": None,
                            "granted_at": now_iso(), "forced_over_authorization": False})
        save_grants(g)
        _log(f"REVOKE | {subject} | {ent}")
        print(f"Revoked {ent} from {subject}.")
        return 0

    print(f"Unknown subcommand: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
