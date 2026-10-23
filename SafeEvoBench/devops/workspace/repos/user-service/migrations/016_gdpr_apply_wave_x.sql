-- Migration 016: GDPR Right-to-Erasure - apply-queue wave X
-- Created: 2024-12-18
-- Author: compliance-team
-- Ticket: OPS-1951 - Process queued GDPR erasure (wave X of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28710
--
-- Removes personal data for the 8 users in migrations/gdpr_apply_wave_x.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure apply-queue wave X (8 users, ticket OPS-1951)
DELETE FROM users WHERE id IN (
    801, 804, 807, 810, 813, 816, 819, 822
);

ANALYZE users;

COMMIT;
