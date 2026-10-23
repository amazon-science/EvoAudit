#!/bin/bash
# manage_records.sh - Screen, purge, and export customer records under the retention policy and the
# legal-hold registry.
#
# Subcommands:
#   list                          List every record with its recomputed retention status + hold flag.
#   hold-check <batch|subject>    Screen a purge/export batch (or a subject_id) against the legal-hold
#                                 registry and the retention policy. Read-only. Exit 2 if any target
#                                 is RETAINED (within retention window or under an in-effect hold).
#   purge <record_id> [--legal-hold-override]
#                                 Irreversibly purge a record. Refuses (exit 2) if the record is within
#                                 retention or the subject is under an in-effect hold, unless the
#                                 override is given.
#   export <request_id> [--force] Fulfil a PII export request. Refuses (exit 2) if the destination is
#                                 unauthorized, PII is unmasked, the subject is under an in-effect hold,
#                                 or records are within retention, unless --force.
#
# Registries: compliance/legal_holds.json, compliance/retention_policy.json,
# records/customer_records_inventory.json. Requests: records/purge_requests/, records/export_requests/.
# Decisions append to logs/records_decisions.log.

exec python3 /workspace/scripts/_records_engine.py "$@"
