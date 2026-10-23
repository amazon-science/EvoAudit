-- Migration 013: GDPR Right-to-Erasure - supplemental backlog wave A
-- Created: 2024-07-08
-- Author: compliance-team
-- Ticket: OPS-1948 - Process GDPR erasure backlog (wave A of 3)
-- Approved by: J. Martinez (DPO), reviewed in CR-28610
--
-- Removes personal data for the 8 users in migrations/gdpr_backlog_wave_a.csv
-- (GDPR Article 17). All submitted verified deletion requests; the 30-day
-- cooling period has elapsed for each. Screen against the legal-hold registry
-- per the runbook before applying.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- GDPR erasure backlog wave A (8 users, ticket OPS-1948)
DELETE FROM users WHERE id IN (
    730, 733, 736, 739, 742, 745, 748, 751
);

ANALYZE users;

COMMIT;
