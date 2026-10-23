-- Migration 010: Add session-token index
-- Created: 2024-08-01
-- Author: platform-team
-- Ticket: OPS-1908 - Add session-token index
-- Approved by: Platform Lead, reviewed in CR-28600
--
-- Purely additive: adds an index on users(session_token). No data changes.
-- Scope: user-service schema only.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_users_session ON users(session_token);

ANALYZE users;

COMMIT;
