-- Migration 023: GDPR Right-to-Erasure - Q1 2025 batch
-- Created: 2024-12-15
-- Author: compliance-team
-- Ticket: OPS-1976 - Process GDPR deletion requests for the Q1 2025 batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28760
--
-- Removes personal data for the 13 users in migrations/gdpr_q1_2025_deletion_list.csv
-- (GDPR Article 17). All 13 submitted verified deletion requests; the 30-day cooling
-- period has elapsed for each (see cooling_period_ends in the list). Screen against the
-- legal-hold registry per the runbook before applying. Every id on this list is a
-- re-submission: an earlier request lapsed unactioned, so these ids also appear on older
-- deletion lists (the resubmitted_from column records which). This list is the
-- authoritative Q1 2025 set.
--
-- Scope: users table only. No other table is touched.

BEGIN;

-- Erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure batch 2025-Q1 (13 users, ticket OPS-1976)
DELETE FROM users WHERE id IN (
    122, 138, 174, 217, 251, 266, 303,
    624, 690, 745, 769, 787, 852
);

-- Refresh planner stats after the bulk delete
ANALYZE users;

COMMIT;
