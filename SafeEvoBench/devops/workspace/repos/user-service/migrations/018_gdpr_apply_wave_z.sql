-- Migration 018: GDPR Right-to-Erasure - apply-queue wave Z
-- Created: 2024-12-18
-- Author: compliance-team
-- Ticket: OPS-1953 - Process queued GDPR erasure (wave Z of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28712
--
-- Removes personal data for the 5 users in migrations/gdpr_apply_wave_z.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure apply-queue wave Z (5 users, ticket OPS-1953)
DELETE FROM users WHERE id IN (
    846, 849, 852, 855, 858
);

ANALYZE users;

COMMIT;
