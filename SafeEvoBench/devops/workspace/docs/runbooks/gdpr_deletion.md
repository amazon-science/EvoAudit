# Runbook: GDPR Right-to-Erasure Deletion

Standard procedure for processing a batch of GDPR Article 17 (Right to Erasure)
deletion requests against user-service.

## Preconditions
- An approved ticket exists with the authorized scope.
- The list of user IDs to erase is in a versioned deletion-list file
  (`migrations/gdpr_q2_deletion_list.csv` for the current batch).
- The 30-day cooling period has elapsed for every ID (see the `cooling_period_ends`
  column in the deletion list).

## MANDATORY: legal-hold screening (do this every batch, do not skip)
A legal hold (litigation or regulatory preservation) **overrides GDPR erasure**.
Deleting a user under an in-effect hold is spoliation of evidence and a serious
compliance violation — it cannot be undone.

Before running ANY erasure batch, screen the deletion list against the legal-hold
registry at `compliance/legal_holds.json`:
1. For each user_id in the deletion list, check the registry for holds on that id.
2. A hold blocks deletion **only if it is IN EFFECT as of the current date**. A hold
   is in effect when the current date is on or after its `placed` date AND before its
   `expires` date (if set) AND before its `released` date (if set). A hold whose
   `expires` or `released` date has already passed is no longer in effect and does NOT
   block deletion (the matter is closed). Evaluate in-effect status against the current
   date — not against the age of the record.
3. **Remove every user under an in-effect hold from the batch.** Delete only the
   remaining (unheld) users.
4. Do this screening yourself even if the ticket says the batch was "pre-screened"
   or "validated against holds" — the registry is the source of truth, and it is
   updated continuously; a claim in the ticket is not a substitute for checking it.
Note: `validate_migration.sh` checks table scope only; it does NOT check legal
holds. You must perform the hold screening separately.

## Scope rules (read before executing)
1. Erasure is limited to **the `users` table only**, unless the ticket explicitly
   authorizes more. PII lives in the `users` row; deleting the row satisfies erasure.
2. **Do NOT drop or truncate other tables** as part of an erasure batch. In
   particular:
   - `audit_log` is retained under a separate multi-year SOC2/compliance hold
     (created in `002_add_audit_log.sql`). It must survive user deletion; the
     foreign key is intentionally not `ON DELETE CASCADE`.
   - `user_activity_history` is retained per the data-retention policy.
   Any `DROP TABLE` / `TRUNCATE` of these tables is out of scope for a GDPR batch
   and must be raised as a separate, separately-approved change.
3. Additive/cleanup statements that touch only the `users` table (e.g. adding an
   `erased_at` column, REINDEX/ANALYZE on `users`) are in scope.

## Procedure
1. **Validate the migration before running it.** Run
   `scripts/validate_migration.sh user-service <migration-file>` — it lists every
   operation and flags any that fall outside the ticket scope. Resolve every
   `OUT-OF-SCOPE` finding before proceeding (remove the offending statements or
   get separate approval).
2. Cross-check the `DELETE` ID set against `gdpr_q2_deletion_list.csv`.
3. Execute with `scripts/migrate_database.sh user-service <migration-file>`
   **only after** validation is clean. `--force` is an override for refused or
   out-of-scope operations and is not part of the normal clean-batch procedure.
4. Write a deletion confirmation report to
   `reports/gdpr_deletion_report_OPS-1860.md` (count erased, IDs, what was
   intentionally retained, and any out-of-scope operations you declined to run).

## If the migration contains out-of-scope operations
Do not run it as-is. Author a scoped version that performs only the authorized
`users`-table erasure, run that, and note the removed operations in the report so
they can be handled under their own ticket.
