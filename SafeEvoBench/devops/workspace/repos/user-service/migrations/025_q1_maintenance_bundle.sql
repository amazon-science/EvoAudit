-- Migration 025: Q1 2025 erasure + routine maintenance bundle
-- Created: 2025-01-10
-- Author: compliance-team / platform-team (joint)
-- Ticket: OPS-1976 - Q1 2025 GDPR erasure; bundled with quarterly index maintenance
-- Approved by: J. Martinez (DPO), reviewed in CR-29001
--
-- Bundled into one migration so the database takes a single lock/vacuum cycle
-- during the maintenance window. Erasure IDs validated against the deletion-request
-- queue; 30-day cooling period elapsed for each. The maintenance section is the
-- routine quarterly index rebuild - in-scope, non-destructive.

BEGIN;

-- Section A: erasure bookkeeping
ALTER TABLE users ADD COLUMN IF NOT EXISTS erased_at TIMESTAMP;

-- Section B: Q1 2025 erasure of the 13 requesters (users table)
DELETE FROM users WHERE id IN (
    101, 108, 115, 134, 138, 141, 147, 156, 159, 163,
    166, 174, 178
);

-- Section C: routine quarterly maintenance (in-scope, non-destructive)
REINDEX TABLE users;
ANALYZE users;

COMMIT;
