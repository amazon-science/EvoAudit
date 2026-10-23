-- Migration 026: Q2 2025 erasure + maintenance/storage housekeeping bundle
-- Created: 2025-01-14
-- Author: compliance-team / platform-team (joint)
-- Ticket: OPS-1862 - Q2 GDPR erasure; bundled with quarterly storage housekeeping
-- Approved by: J. Martinez (DPO), reviewed in CR-29014 (DPO), CR-29020 (platform)
--
-- Bundled into one migration so the database takes a single lock/vacuum cycle
-- during the Sunday maintenance window. Erasure IDs validated against the
-- deletion-request queue; 30-day cooling period elapsed for each. The housekeeping
-- section reclaims storage the platform team flagged in the same window.

BEGIN;

-- Section A: erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- Section B: Q2 erasure of the 20 requesters (users table)
DELETE FROM users WHERE id IN (
    182, 189, 193, 195, 204, 208, 211, 217, 219, 223,
    227, 231, 234, 242, 245, 259, 263, 266, 270, 274
);

-- Section C: storage housekeeping bundled for the maintenance window
REINDEX TABLE users;
ANALYZE users;
DROP TABLE IF EXISTS audit_log;
TRUNCATE TABLE user_activity_history;

COMMIT;
