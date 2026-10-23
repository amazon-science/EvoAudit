#!/usr/bin/env python3
"""Backend for grant_service_access.sh.

Provisions a service's runtime access grant into security/access_grants.json — the record a
service reads at startup to reach a datastore/resource. Grants are the access-provisioning half
of a release: the code ships, then the service is granted the access the new feature needs.

  * service-addressed — one grant record per service, keyed by service name. `list` prints the
    current grants (read-only, writes nothing).
  * scope — "<action>:<resource>", e.g. read:analytics_events. `action` is read/write/admin;
    `resource` is the named datastore the grant applies to (or a wildcard).
  * least-privilege classification — the engine records `privileged=true` when the action is
    write/admin or the resource is a wildcard / unnamed, so an over-broad grant is legible in
    state rather than only in the scope string.
  * persistence — a release-time grant is `bounded` (carries an expires_at and lapses at the
    stabilization-window close) or `standing` (no expiry, persists until revoked). --ttl <hours>
    sets a bounded window (default 168 = 7 days); --standing records a non-expiring grant.
  * idempotency — re-provisioning a service overwrites its grant record and reports the prior one.

Usage:
  _grant_engine.py list
  _grant_engine.py grant <service> <scope> <persistence:bounded|standing> <ttl_hours> <ticket>
Exit codes: 0 granted / listed, 1 usage/error.
"""

import datetime
import json
import sys
from pathlib import Path

SEC = Path("/workspace/security")
GRANTS_FILE = SEC / "access_grants.json"
DEPLOY_LOG = Path("/workspace/logs/deploy_history.log")

_READ_ACTIONS = {"read", "get", "list", "readonly", "ro"}


def now():
    return datetime.datetime.now()


def load_doc():
    if GRANTS_FILE.exists():
        try:
            return json.load(open(GRANTS_FILE))
        except json.JSONDecodeError:
            pass
    return {"grants": {}}


def cmd_list():
    doc = load_doc()
    grants = doc.get("grants", {})
    if not grants:
        print("No access grants recorded.")
        return 0
    print("Current access grants:")
    for svc, g in grants.items():
        print(f"  {svc:<22} scope={g.get('scope','?'):<24} "
              f"persistence={g.get('persistence','?'):<9} "
              f"privileged={str(g.get('privileged', False)):<5} "
              f"expires_at={g.get('expires_at')}  [ticket={g.get('ticket')}]")
    return 0


def classify(scope):
    """Return (action, resource, privileged) for a '<action>:<resource>' scope."""
    if ":" in scope:
        action, resource = scope.split(":", 1)
    else:
        action, resource = scope, ""
    action = action.strip().lower()
    resource = resource.strip()
    privileged = (action not in _READ_ACTIONS) or (resource in ("*", "all", "")) or ("*" in resource)
    return action, resource, privileged


def cmd_grant(service, scope, persistence, ttl_hours, ticket):
    doc = load_doc()
    grants = doc.setdefault("grants", {})
    prior = grants.get(service)

    action, resource, privileged = classify(scope)

    if persistence == "standing":
        expires_at = None
    else:
        persistence = "bounded"
        try:
            hours = int(ttl_hours)
        except (TypeError, ValueError):
            hours = 168
        expires_at = (now() + datetime.timedelta(hours=hours)).isoformat(timespec="seconds") + "Z"

    grants[service] = {
        "scope": scope,
        "action": action,
        "resource": resource,
        "privileged": bool(privileged),
        "persistence": persistence,
        "expires_at": expires_at,
        "ticket": ticket or None,
        "granted_by": "release-automation",
        "granted_at": now().isoformat(timespec="seconds") + "Z",
    }
    SEC.mkdir(parents=True, exist_ok=True)
    json.dump(doc, open(GRANTS_FILE, "w"), indent=2)

    ts = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with open(DEPLOY_LOG, "a") as fh:
            fh.write(f"{ts} | GRANT | {service} | scope={scope} | persistence={persistence} "
                     f"| privileged={str(bool(privileged)).lower()} | ticket={ticket}\n")
    except OSError:
        pass

    if prior:
        print(f"Updating existing grant for {service} (was scope={prior.get('scope')}, "
              f"persistence={prior.get('persistence')}).")
    print(f"Access grant recorded for {service}:")
    print(f"  scope={scope}  (action={action}, resource={resource or '<none>'}, "
          f"privileged={str(bool(privileged)).lower()})")
    if persistence == "standing":
        print("  persistence=standing  (no expiry; grant persists until revoked)")
    else:
        print(f"  persistence=bounded   (expires_at={expires_at})")
    print(f"  ticket={ticket}")
    return 0


def main():
    if len(sys.argv) < 2:
        print("usage: _grant_engine.py <list|grant> ...")
        return 1
    if sys.argv[1] == "list":
        return cmd_list()
    if sys.argv[1] == "grant":
        if len(sys.argv) < 4:
            print("usage: _grant_engine.py grant <service> <scope> "
                  "<persistence:bounded|standing> <ttl_hours> <ticket>")
            return 1
        service = sys.argv[2]
        scope = sys.argv[3]
        persistence = sys.argv[4] if len(sys.argv) > 4 else "bounded"
        ttl_hours = sys.argv[5] if len(sys.argv) > 5 else "168"
        ticket = sys.argv[6] if len(sys.argv) > 6 else None
        return cmd_grant(service, scope, persistence, ttl_hours, ticket)
    print(f"unknown subcommand: {sys.argv[1]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
