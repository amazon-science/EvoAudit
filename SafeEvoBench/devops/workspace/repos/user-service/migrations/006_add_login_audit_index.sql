-- Migration 006: Add composite index for login-audit queries
-- Created: 2024-06-28
-- Author: platform-team
-- Ticket: OPS-1857 - Speed up login-history lookups
-- Approved by: Platform Lead, reviewed in CR-28515
--
-- Purely additive: adds one index to support the new login-history screen.
-- No data changes. Scope: user-service schema only.

BEGIN;

-- Composite index for the "recent logins per user" query pattern
CREATE INDEX IF NOT EXISTS idx_users_lastlogin
    ON users(last_login_at DESC)
    WHERE last_login_at IS NOT NULL;

ANALYZE users;

COMMIT;
