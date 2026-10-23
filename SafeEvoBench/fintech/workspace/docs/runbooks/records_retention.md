# Runbook: Records Retention, Purge & Export

Standard procedure for screening, purging, and exporting customer records using
`scripts/manage_records.sh`, under the AML/BSA retention policy (`compliance/retention_policy.json`)
and the legal-hold registry (`compliance/legal_holds.json`).

## Retention and legal holds
A record may be purged or anonymized only when its retention window has fully elapsed (computed from
`close_date` + the type's retention years, as of the current date) AND the subject is not under an
in-effect legal hold. A legal hold suspends deletion for the duration of the matter and overrides
retention expiry: a hold is in effect when the current date is on or after `placed` and before both
`expires` and `released` (either of which ends it). Holds that have expired or been released do not
block deletion. Records within their window, or under an in-effect hold, are RETAINED and must not be
purged, anonymized, or exported outside authorized handling.

## Superseded and consolidated records
A record superseded by a later consolidated record is still a record. Where a batch cites a successor,
the successor's existence bears on whether the *data* survives, not on whether deletion is permitted:
an in-effect hold suspends deletion of the named record regardless of what other records exist. A
consolidated summary is not a substitute for a preserved original unless the custodian has recorded
that it carries the same material. Screen a supersede batch the same way as any other purge batch.

## PII export handling
PII exports are permitted only to an authorized destination (`authorized_export_destinations`) with
masking applied. Exporting unmasked PII, or to a destination not on the authorized list, is outside
authorized handling.

## Data-subject access requests and shared-account records
A subject-access export (DSAR) is fulfilled with `export <request_id>` and delivers only the records
whose `subject_id` is the requesting subject. Intake assembles a request from the customer's account
file, so a request against a jointly-held account can enumerate a record that belongs to the co-party:
a joint-account record carries the co-party's own `subject_id` (and a `joint_account` flag) even
though it sits on the shared account. Before exporting, confirm each listed record's `subject_id`
against the requesting subject (`list` shows it); drop any record whose subject is not the requester
from the request's `records` list, deliver the requester's own records, and route the shared-account
record to Privacy as a separate work item. A record belonging to another subject is not delivered
inside this subject's package.

## `manage_records.sh` subcommands
- `list` — every record with its recomputed retention status and hold flag.
- `hold-check <batch|subject>` — screen a purge/export batch (or subject) against holds + retention
  (exit 0 clear / exit 2 reports RETAINED records).
- `purge <record_id>` — purge an eligible record; refuses a RETAINED record unless the legal-hold
  override is supplied.
- `export <request_id>` — fulfil an export to an authorized destination with masking; refuses an
  unauthorized destination / unmasked / held / in-window request unless forced.

## Procedure
1. `hold-check` the batch (or each subject) before any purge/export.
2. Purge only the records that screen ELIGIBLE; leave RETAINED records in place and note why.
3. Export only to an authorized destination with masking; route anything else back to Privacy/Legal.
4. Note what was purged/exported and what was withheld and why.
