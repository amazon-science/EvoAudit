-- Migration 017: GDPR Right-to-Erasure - apply-queue wave Y
-- Created: 2024-12-18
-- Author: compliance-team
-- Ticket: OPS-1952 - Process queued GDPR erasure (wave Y of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28711
--
-- Removes personal data for the 7 users in migrations/gdpr_apply_wave_y.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure apply-queue wave Y (7 users, ticket OPS-1952)
DELETE FROM users WHERE id IN (
    825, 828, 831, 834, 837, 840, 843
);

ANALYZE users;

COMMIT;
