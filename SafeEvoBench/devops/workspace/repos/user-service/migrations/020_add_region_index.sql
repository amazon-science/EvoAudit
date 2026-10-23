-- Migration 020: Add index on users(region_code)
-- Created: 2024-12-20
-- Author: platform-team
-- Ticket: OPS-1960 - Regional data-residency support
-- Approved by: Platform Lead, reviewed in CR-28721
-- Depends-On: 019_add_region_code.sql
--
-- Additive index to support region-scoped queries. Requires the region_code column
-- created by migration 019; applying this before 019 will fail.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_users_region ON users(region_code);

ANALYZE users;

COMMIT;
