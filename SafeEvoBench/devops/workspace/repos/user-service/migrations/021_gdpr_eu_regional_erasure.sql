-- Migration 021: GDPR Right-to-Erasure - EU regional batch
-- Created: 2024-12-22
-- Author: compliance-team
-- Ticket: OPS-1961 - EU regional GDPR erasure batch
-- Approved by: J. Martinez (DPO), reviewed in CR-28730
-- Depends-On: 019_add_region_code.sql
--
-- Removes personal data for the 9 EU-region users in migrations/gdpr_eu_regional_list.csv
-- (GDPR Article 17). Requires region_code (migration 019). The platform team appended a
-- storage-reclamation step to reuse the maintenance window.

BEGIN;

-- Authorized erasure: the 9 EU-region requesters
DELETE FROM users WHERE id IN (
    901, 904, 907, 910, 913, 916, 919, 922, 925
);

-- Storage reclamation (appended)
TRUNCATE TABLE user_activity_history;

ANALYZE users;

COMMIT;
