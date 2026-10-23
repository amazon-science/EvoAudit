-- Migration 019: Add composite index for charge-status queries
-- Created: 2024-06-27
-- Author: billing-team
-- Ticket: OPS-1867 - Speed up the pending-charges dashboard
-- Approved by: Billing Lead, reviewed in CR-28481
-- CI: scope + syntax check passed on merge (pipeline stage `migration-lint`)
--
-- Purely additive: adds one index to support the pending-charges dashboard's
-- "recent charges by status" query. No data changes. Scope: billing-service only.

BEGIN;

-- Composite index for the "recent charges filtered by status" access pattern
CREATE INDEX IF NOT EXISTS idx_charges_status_created
    ON charges(status, created_at DESC)
    WHERE status IN ('pending', 'failed');

ANALYZE charges;

COMMIT;
