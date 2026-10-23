-- Migration 021: Purge closed-invoice records past retention (FY2019)
-- Ticket OPS-1974. Closed invoices purged 5 years after close; these FY2019 records are eligible.
BEGIN;
DELETE FROM invoices WHERE invoice_id IN (
  'INV-2019-0021','INV-2019-0164','INV-2019-0302','INV-2019-0489','INV-2019-0577'
);
COMMIT;
