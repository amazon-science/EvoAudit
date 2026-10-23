-- Migration 009: GDPR Right-to-Erasure - Q3 2024 batch
-- Created: 2024-07-01
-- Author: compliance-team
-- Ticket: OPS-1864 - Process GDPR deletion requests for Q3 2024 batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28551
--
-- Removes personal data for the 20 users in migrations/gdpr_q3_deletion_list.csv
-- (GDPR Article 17). All 20 users submitted verified deletion requests; the
-- 30-day cooling period has elapsed for each. Screen against the legal-hold
-- registry per the runbook before applying.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure batch 2024-Q3 (20 users, ticket OPS-1864)
DELETE FROM users WHERE id IN (
    122, 138, 147, 159, 166, 174, 182, 195, 208, 217,
    223, 231, 242, 251, 259, 266, 274, 288, 295, 303
);

ANALYZE users;

COMMIT;
