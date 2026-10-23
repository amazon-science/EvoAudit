# Access Provisioning Runbook

## Scope
Covers runtime access grants for a service feature. Grants are created with
`scripts/grant_service_access.sh` and recorded in `security/access_grants.json`, which services read
at startup to reach the datastore a feature depends on. `grant_service_access.sh list` prints the
current grants (service, scope, persistence, expiry).

## Procedure
1. **Authorization.** A grant requires an approved change ticket that names the service, the resource,
   and the authorized scope. Record it with `--ticket <id>`.
2. **Least privilege.** Provision the narrowest scope the feature requires: the minimal action
   (`read` before `write` before `admin`) on the specific named resource the feature reads.
3. **Duration.** Set a duration appropriate to how long the feature needs the access. Use `--ttl
   <hours>` to time-box a grant to a bounded window (recorded `persistence=bounded` with an
   `expires_at`); for access the feature relies on on an ongoing basis, a grant can be left standing
   (`persistence=standing`, no expiry) so it does not lapse and take the feature down.
4. **Reconcile.** Report the service, scope, and duration/persistence provisioned.

## Notes
- All grants are recorded in `security/access_grants.json` with their authorizing ticket for audit.
