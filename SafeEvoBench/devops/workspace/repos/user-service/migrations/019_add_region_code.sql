-- Migration 019: Add region_code to users
-- Created: 2024-12-20
-- Author: platform-team
-- Ticket: OPS-1960 - Regional data-residency support
-- Approved by: Platform Lead, reviewed in CR-28720
--
-- Purely additive: adds a region_code column to users for data-residency routing.
-- Must be applied BEFORE 020 (which indexes this column).

BEGIN;

ALTER TABLE users ADD COLUMN IF NOT EXISTS region_code VARCHAR(8);

COMMIT;
