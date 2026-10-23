-- Migration 016: Purge closed-invoice records past retention (FY2017)
-- Ticket OPS-1972. Data-retention policy: closed invoices are purged 5 years after close.
-- These FY2017 invoices closed in 2017 and are now well past the retention window.
BEGIN;
DELETE FROM invoices WHERE invoice_id IN (
  'INV-2017-0007','INV-2017-0142','INV-2017-0288','INV-2017-0391','INV-2017-0455',
  'INV-2017-0512','INV-2017-0673','INV-2017-0724'
);
COMMIT;
