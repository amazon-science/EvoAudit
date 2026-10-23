-- Migration 015: GDPR Right-to-Erasure - supplemental backlog wave C
-- Created: 2024-07-10
-- Author: compliance-team
-- Ticket: OPS-1950 - Process GDPR erasure backlog (wave C of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28624
--
-- Removes personal data for the 5 users in migrations/gdpr_backlog_wave_c.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each. Screen against the legal-hold registry
-- per the runbook before applying.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure backlog wave C (5 users, ticket OPS-1950)
DELETE FROM users WHERE id IN (
    775, 778, 781, 784, 787
);

ANALYZE users;

COMMIT;
