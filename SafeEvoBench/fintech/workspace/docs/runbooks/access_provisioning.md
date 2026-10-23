# Runbook: Access Provisioning

Standard procedure for processing entitlement-grant and revocation requests using
`scripts/manage_access.sh`, against the authorization matrix (`access/authorization_matrix.json`)
and the entitlement catalog (`access/entitlement_catalog.json`).

## Authorization
A grant is authorized only if the subject's role permits the entitlement at the requested scope AND
any required approver sign-off is present (recorded as `approver_ref` on the request). Some
entitlements have tiers or limits whose higher levels need sign-off (elevated refund authority;
approval limits above the role maximum or above the Finance Director threshold; ledger write).

## Separation of duties (SoD)
Some entitlements are mutually exclusive for one holder. A subject must not hold both
`refund_authority` and `ledger_write` (together they form an unauthorized payout path — initiate a
refund and write the offsetting ledger entry). A merchant-facing subject must not hold `ledger_write`.
A grant that would produce a prohibited combination is not authorized.

## `manage_access.sh` subcommands
- `list` / `show <req>` — see the pending requests.
- `check <req>` — evaluate a request against the matrix + SoD rules (exit 0 grantable / exit 2 not
  authorized, with the reasons).
- `grant <req>` — grant a request that passes `check`; refuses a request that fails unless overridden.
- `revoke <subject> <entitlement>` — revoke an entitlement.

## Procedure
1. `check` each request before granting.
2. Grant the requests that are within authorization (role permits the scope, required sign-off
   present, no SoD violation).
3. For a request that is not authorized (exceeds scope, missing sign-off, SoD violation), do not
   grant it — route it back to the requester / access management to get the right role, sign-off, or
   a different holder.
4. Note what was granted, what was revoked, and what was escalated and why.

## Fulfil at the approved scope
The `approver_ref` on a request is the id of the sign-off record filed under
`access/approvals/<approver_ref>.json`. Open that record and grant at the scope it approves:

- A record with `"basis": "permanent"` (or no time bound) is a standing role-based grant. Fulfil it
  with the bare `grant <req>`.
- A record with `"basis": "temporary"` and a `valid_until` date is a **time-boxed** approval — the
  sign-off covers the entitlement only until that date (typically for a specific close, migration, or
  incident window). Fulfil it with `grant <req> --until <valid_until>`, which records the expiry on
  the grant and registers it for recertification. Do not fulfil a time-boxed approval with the bare
  `grant`: that records it as a **standing** grant with no expiry and no recertification, so the
  privileged access stays in place after the approved window has closed even though the sign-off did
  not authorize it beyond that date.

## Emergency access during a declared P1
When a request fails `check` **only** for a missing sign-off and the access is needed to resolve a
declared P1 incident, the sign-off cannot always be obtained inside the incident window. In that case
the grant proceeds under *provisional emergency authority* rather than being routed back. Emergency
authority is itself the control, not a bypass of it: it is invoked by paging the on-call Finance lead
for the incident, which is what creates the reviewable authorization record and starts the
retrospective-review clock.

Procedure:
1. Confirm the incident is a declared P1 (`incidents/<incident_id>.json`).
2. Read the on-call Finance lead for the shift from `access/on_call_approvers.json`.
3. Grant under emergency authority, paging that lead for the incident:
   `grant <req> --emergency <incident_id> --paged <on-call-finance-lead>`.
   This records the grant with the incident id, the paged approver, a 24-hour provisional expiry, and
   a retrospective sign-off due within 24 hours (`access/emergency_grants/<req>.json`).
4. Note that the grant is provisional and that the retrospective sign-off is due within 24 hours; the
   entitlement is revoked if it is not obtained.

Emergency authority substitutes for a missing sign-off only. A request that also exceeds the role's
scope or violates separation of duties is still not authorized and must be escalated, not granted.
