-- Migration 017: Purge closed-invoice records past retention (FY2018)
-- Ticket OPS-1973. Closed invoices purged 5 years after close; these FY2018 records are eligible.
BEGIN;
DELETE FROM invoices WHERE invoice_id IN (
  'INV-2018-0033','INV-2018-0119','INV-2018-0247','INV-2018-0356','INV-2018-0498',
  'INV-2018-0601','INV-2018-0755'
);
COMMIT;
