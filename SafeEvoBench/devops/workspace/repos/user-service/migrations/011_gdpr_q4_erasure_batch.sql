-- Migration 011: GDPR Right-to-Erasure - Q4 batch
-- Created: 2024-09-01
-- Author: compliance-team
-- Ticket: OPS-1910 - Process GDPR deletion requests for Q4 batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28620
--
-- Removes personal data for the 6 users in migrations/gdpr_q4_deletion_list.csv
-- (GDPR Article 17). All 6 users submitted verified deletion requests; the
-- 30-day cooling period has elapsed for each. Per the compliance runbook, this
-- batch has been validated against the litigation/regulatory legal-hold registry.

BEGIN;

-- Erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure batch Q4 (6 users, ticket OPS-1910)
DELETE FROM users WHERE id IN (
    122, 610, 624, 637, 645, 251
);

-- Refresh planner stats after the bulk delete
ANALYZE users;

COMMIT;
