-- Migration 002: Add audit_log table for security event tracking
-- Created: 2023-11-02
-- Author: security-team
-- Ticket: SEC-442 - Implement audit logging for compliance

BEGIN;

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type VARCHAR(50) NOT NULL,
    details TEXT,
    ip_address VARCHAR(45),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Index for querying user-specific audit history
CREATE INDEX idx_audit_log_user_id ON audit_log(user_id);

-- Index for time-range queries (compliance reporting)
CREATE INDEX idx_audit_log_created_at ON audit_log(created_at);

-- Composite index for common query pattern: user events in time range
CREATE INDEX idx_audit_log_user_time ON audit_log(user_id, created_at DESC);

COMMENT ON TABLE audit_log IS 'Security audit trail for user actions - required for SOC2 compliance';
COMMENT ON COLUMN audit_log.event_type IS 'One of: login, logout, permission_change, data_access, password_reset, account_lock';

COMMIT;
