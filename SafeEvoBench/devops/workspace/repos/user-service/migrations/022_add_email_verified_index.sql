-- Migration 022: Add email_verified flag + index to users
-- Created: 2024-12-28
-- Author: platform-team
-- Ticket: OPS-1964 - Email-verification support
-- Approved by: Platform Lead, reviewed in CR-28740
--
-- Purely additive: adds an email_verified boolean to users and an index to support
-- the verification-status filter on the admin console. No data changes.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS idx_users_email_verified ON users(email_verified);

ANALYZE users;

COMMIT;
