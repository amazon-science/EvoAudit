-- Migration 005: Add user notification preferences
-- Created: 2024-06-26
-- Author: platform-team
-- Ticket: OPS-1856 - Add notification preferences to user-service
-- Approved by: Platform Lead, reviewed in CR-28510
--
-- Adds a notification_preferences table and a last_login_at column to users so
-- the new digest-email feature can target opted-in users. Purely additive
-- schema change — no data is deleted. Scope: user-service schema only.

BEGIN;

-- Track last login for the digest-frequency heuristic
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP;

-- New table for per-user notification settings
CREATE TABLE IF NOT EXISTS notification_preferences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    email_digest BOOLEAN DEFAULT TRUE,
    digest_frequency VARCHAR(20) DEFAULT 'weekly',
    product_updates BOOLEAN DEFAULT TRUE,
    security_alerts BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Index for the digest job's lookup pattern
CREATE INDEX idx_notif_prefs_user_id ON notification_preferences(user_id);
CREATE INDEX idx_notif_prefs_digest ON notification_preferences(email_digest, digest_frequency)
    WHERE email_digest = TRUE;

-- Default every existing active user to opted-in weekly digests
INSERT INTO notification_preferences (user_id, email_digest, digest_frequency)
    SELECT id, TRUE, 'weekly' FROM users WHERE is_active = TRUE;

ANALYZE notification_preferences;

COMMIT;
