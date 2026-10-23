-- Migration 028: Clear the stale admin-console query cache
-- Created: 2025-01-05
-- Author: platform-team
-- Ticket: OPS-21028 - Quarterly query-cache maintenance
-- Approved by: Platform Lead, reviewed in CR-291028
--
-- The query_cache is a materialized cache rebuilt on demand; clearing it is routine
-- maintenance authorized under OPS-21028. No user data is touched.

BEGIN;

TRUNCATE TABLE query_cache;

COMMIT;
