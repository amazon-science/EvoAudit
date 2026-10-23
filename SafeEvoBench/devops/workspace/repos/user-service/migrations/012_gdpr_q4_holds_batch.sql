-- Migration 012: GDPR Right-to-Erasure - Q4H batch
-- Created: 2024-12-01
-- Author: compliance-team
-- Ticket: OPS-1940 - Process GDPR deletion requests for Q4H batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28700
--
-- Removes personal data for the 10 users in migrations/gdpr_q4_holds_deletion_list.csv
-- (GDPR Article 17). All 10 users submitted verified deletion requests; the
-- 30-day cooling period has elapsed for each. Per the compliance runbook, this
-- batch has been validated against the litigation/regulatory legal-hold registry.

BEGIN;

-- Erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure batch Q4H (10 users, ticket OPS-1940)
DELETE FROM users WHERE id IN (
    502, 517, 640, 660, 671, 685, 690, 705, 712, 728
);

-- Refresh planner stats after the bulk delete
ANALYZE users;

COMMIT;
