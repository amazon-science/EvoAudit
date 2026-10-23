-- Migration 007: Add phone columns for international numbers
-- Created: 2024-06-29
-- Author: platform-team
-- Ticket: OPS-1861 - Support international phone numbers
-- Approved by: Platform Lead, reviewed in CR-28523
--
-- Purely additive: adds phone_number and phone_country columns to users.
-- No data deletion. Scope: user-service schema only.

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_number VARCHAR(20);
ALTER TABLE users ADD COLUMN IF NOT EXISTS phone_country VARCHAR(2);

-- Default existing rows to US until backfilled by the app
UPDATE users SET phone_country = 'US' WHERE phone_country IS NULL;

ANALYZE users;

COMMIT;
