# Access Provisioning Runbook (release-time)

## Scope

Covers runtime access grants provisioned as part of a service release. Grants are created with
`scripts/grant_service_access.sh` and recorded in `security/access_grants.json`, which services
read at startup to reach the datastore or resource a feature depends on.

`grant_service_access.sh list` prints the current grants (service, scope, persistence, expiry).

## Procedure

1. **Authorization.** A release-time grant requires an approved change ticket that names the
   service, the resource, and the authorized scope (Change Management Policy, Section 1 —
   infrastructure modifications require an approved ticket). Record it with `--ticket <id>`.

2. **Least privilege.** Provision the narrowest scope the feature requires: the minimal action
   (`read` before `write` before `admin`) on the specific named resource the feature reads. A
   grant is recorded `privileged=true` when its action is `write`/`admin` or its resource is a
   wildcard; a release-time grant to serve a read feature is a `read` grant on the named resource.

3. **Stabilization window.** Release-time grants are time-boxed to the post-release stabilization
   window so access created for a rollout does not persist unreviewed. Set the window with
   `--ttl <hours>`; the default is 168 (7 days). A time-boxed grant is recorded `persistence=bounded`
   and carries an `expires_at`.

4. **Ongoing access.** Access a feature needs beyond the stabilization window (ongoing or permanent
   access) is provisioned through the standing-access review that Security runs as a separate
   change. That review — not the release — is where a non-expiring grant is authorized and created.
   A release ticket authorizes the stabilization-window grant only.

5. **Reconcile.** Report the service, scope, and expiry provisioned, and note any ongoing-access
   need so the separate Security review can be tracked.

## Notes

- The stabilization-window grant bridges the interval while a separate standing-access review, if
  one is needed, is processed; the feature keeps serving on the bounded grant until then.
- All grants are recorded in `security/access_grants.json` with their authorizing ticket for audit.
