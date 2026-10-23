-- Migration 020: Add ISO currency code to charges
-- Created: 2024-06-28
-- Author: billing-team
-- Ticket: OPS-1868 - Prepare charges for multi-currency billing
-- Approved by: Billing Lead, reviewed in CR-28489
-- CI: scope + syntax check passed on merge (pipeline stage `migration-lint`)
--
-- Purely additive: charges gain an ISO-4217 currency_code column ahead of the
-- multi-currency rollout; existing rows default to 'USD'. No data is removed.
-- Scope: billing-service schema only.

BEGIN;

-- ISO-4217 currency code; existing charges are all USD today
ALTER TABLE charges ADD COLUMN IF NOT EXISTS currency_code VARCHAR(3) DEFAULT 'USD';

-- Backfill any NULLs (defensive; the DEFAULT already covers existing rows)
UPDATE charges SET currency_code = 'USD' WHERE currency_code IS NULL;

ANALYZE charges;

COMMIT;
