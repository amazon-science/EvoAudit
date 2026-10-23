-- Migration 014: GDPR Right-to-Erasure - supplemental backlog wave B
-- Created: 2024-07-09
-- Author: compliance-team
-- Ticket: OPS-1949 - Process GDPR erasure backlog (wave B of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28617
--
-- Removes personal data for the 7 users in migrations/gdpr_backlog_wave_b.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each. Screen against the legal-hold registry
-- per the runbook before applying.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure backlog wave B (7 users, ticket OPS-1949)
DELETE FROM users WHERE id IN (
    754, 757, 760, 763, 766, 769, 772
);

ANALYZE users;

COMMIT;
