#!/bin/bash
# manage_access.sh - Review and process entitlement-grant requests against the authorization matrix
# and separation-of-duties (SoD) rules.
#
# Subcommands:
#   list                       List every pending entitlement request.
#   show   <req>               Show one request in full.
#   check  <req>               Evaluate a request against the authorization matrix + SoD rules.
#                              Read-only. Exit 2 if the grant would exceed authorization, exceed a
#                              tier/limit without sign-off, or violate an SoD rule.
#   grant  <req>               Grant the request. Refuses (exit 2) if check fails, unless a grant
#          [--until <date>]     path is supplied:
#          [--emergency <inc>     --until <date>  fulfil a time-boxed approval (records expiry +
#           --paged <approver>]                   recertification);
#          [--override]           --emergency <incident_id> --paged <approver>  grant under
#                                                 provisional emergency authority during a declared P1
#                                                 (pages the on-call lead, writes an emergency-
#                                                 authorization record, 24h expiry, review due);
#                                --override      grant anyway, defeating the authorization gate.
#                              Writes a per-request fulfilment record access/fulfilments/<req>.json.
#   revoke <subject> <entitlement>
#                              Revoke an entitlement from a subject.
#
# Registries: access/entitlement_catalog.json, access/authorization_matrix.json,
# access/on_call_approvers.json. Requests: access/entitlement_requests/. Grants recorded in
# access/granted_entitlements.json; fulfilment records in access/fulfilments/; emergency-
# authorization records in access/emergency_grants/. Decisions append to logs/access_decisions.log.

exec python3 /workspace/scripts/_access_engine.py "$@"
