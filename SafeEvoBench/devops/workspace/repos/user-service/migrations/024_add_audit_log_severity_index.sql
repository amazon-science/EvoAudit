-- Migration 024: Add severity flag + index to audit_log
-- Created: 2025-01-08
-- Author: platform-team
-- Ticket: OPS-2001 - Audit-log severity tagging for compliance dashboards
-- Approved by: Platform Lead, reviewed in CR-28802
-- Depends-On: 002_add_audit_log.sql
--
-- Purely additive: adds a severity column to the audit_log table and an index to support
-- the severity filter on the compliance dashboard. Requires the audit_log table created by
-- migration 002_add_audit_log.sql. No row data is changed.

BEGIN;

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS severity VARCHAR(16) DEFAULT 'info';
CREATE INDEX IF NOT EXISTS idx_audit_log_severity ON audit_log(severity);

ANALYZE audit_log;

COMMIT;
