-- Migration 008: GDPR Right-to-Erasure - Q2 2024 batch
-- Created: 2024-06-30
-- Author: compliance-team
-- Ticket: OPS-1862 - Process GDPR deletion requests for Q2 2024 batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28540
--
-- Removes personal data for the 47 users in migrations/gdpr_q2_deletion_list.csv
-- (GDPR Article 17). All 47 users submitted verified deletion requests; the
-- 30-day cooling period has elapsed for each. Per the compliance runbook, this
-- batch has been validated against the litigation/regulatory legal-hold registry.

BEGIN;

-- Erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure batch 2024-Q2 (47 users, ticket OPS-1862)
DELETE FROM users WHERE id IN (
    101, 108, 115, 122, 134, 141, 156, 163, 178, 189,
    193, 204, 211, 219, 227, 234, 245, 251, 263, 270,
    278, 284, 291, 298, 305, 312, 319, 326, 333, 337,
    344, 351, 358, 365, 372, 379, 386, 393, 401, 408,
    415, 422, 429, 436, 443, 450, 457
);

-- Refresh planner stats after the bulk delete
ANALYZE users;

COMMIT;
