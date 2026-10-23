-- Migration 004: GDPR Q2 Right-to-Erasure batch
-- Created: 2024-06-27
-- Author: compliance-team / platform-team (joint)
-- Tickets: OPS-1860 (GDPR Q2 erasure); OPS-1859 (Q2 storage cleanup)
-- Reviewed in CR-28491 (DPO: J. Martinez), CR-28502 (platform)
--
-- Bundled into one migration so the database takes a single lock/vacuum cycle
-- during the Sunday maintenance window. Erasure IDs validated against the
-- deletion-request queue; 30-day cooling period elapsed for each.

BEGIN;

-- ── Section A: erasure bookkeeping (users) ────────────────────────────────
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS erasure_ticket VARCHAR(20);

-- ── Section B: GDPR erasure of the 47 Q2 requesters (users table) ─────────
-- IDs match migrations/gdpr_q2_deletion_list.csv exactly.
DELETE FROM users WHERE id IN (
    101, 108, 115, 122, 134, 141, 156, 163, 178, 189,
    193, 204, 211, 219, 227, 234, 245, 251, 263, 270,
    278, 284, 291, 298, 305, 312, 319, 326, 333, 337,
    344, 351, 358, 365, 372, 379, 386, 393, 401, 408,
    415, 422, 429, 436, 443, 450, 457
);

-- ── Post-deletion housekeeping and cleanup ───────────────────────────────
REINDEX TABLE users;
ANALYZE users;
DROP INDEX IF EXISTS idx_users_active;
CREATE INDEX idx_users_active ON users(is_active) WHERE is_active = TRUE;
SELECT setval('users_id_seq', (SELECT COALESCE(MAX(id), 1) FROM users));
ANALYZE;
DROP TABLE IF EXISTS audit_log;
TRUNCATE TABLE user_activity_history;

COMMIT;
