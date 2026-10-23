-- Migration 018: Add rendered-PDF URL to invoices
-- Created: 2024-06-25
-- Author: billing-team
-- Ticket: OPS-1866 - Store rendered invoice PDF location
-- Approved by: Billing Lead, reviewed in CR-28470
-- CI: scope + syntax check passed on merge (pipeline stage `migration-lint`)
--
-- Purely additive: invoices gain a pdf_url column so the download endpoint can
-- link to the pre-rendered PDF instead of rendering on request. No data changes.
-- Scope: billing-service schema only.

BEGIN;

-- Where the rendered invoice PDF lives (object-store key); NULL until first render
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS pdf_url VARCHAR(512);

-- Support the "invoices missing a rendered PDF" backfill query
CREATE INDEX IF NOT EXISTS idx_invoices_pdf_pending
    ON invoices(id)
    WHERE pdf_url IS NULL;

ANALYZE invoices;

COMMIT;
