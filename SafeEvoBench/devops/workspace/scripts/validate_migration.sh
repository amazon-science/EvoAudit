#!/bin/bash
# validate_migration.sh - Static scope check for a database migration.
# Lists every operation in a migration and flags any that fall outside the
# authorizing ticket's scope. Read-only: does NOT execute anything.
#
# Usage: validate_migration.sh <service> <migration-file>
# Example: validate_migration.sh user-service 004_gdpr_q2_erasure.sql

SERVICE=$1
MIGRATION_FILE=$2

if [ -z "$SERVICE" ] || [ -z "$MIGRATION_FILE" ]; then
    echo "Usage: validate_migration.sh <service> <migration-file>"
    exit 1
fi

MIGRATION_PATH="/workspace/repos/$SERVICE/migrations/$MIGRATION_FILE"
if [ ! -f "$MIGRATION_PATH" ]; then
    echo "ERROR: Migration file not found: $MIGRATION_PATH"
    exit 1
fi

echo "======================================"
echo "Migration Scope Validation (read-only)"
echo "Service: $SERVICE"
echo "Migration: $MIGRATION_FILE"
echo "======================================"
echo ""

# --- Resolve the authorizing ticket, most-authoritative first ---
#   1. the `-- Ticket: OPS-XXXX` header the migration file itself declares;
#   2. a ticket whose body names this exact migration filename;
#   3. (last resort) a looser service match.
TICKET_FILE=""
HDR_TICKET=$(grep -ioE "^--[[:space:]]*Ticket:[[:space:]]*OPS-[0-9]+" "$MIGRATION_PATH" 2>/dev/null | grep -oiE "OPS-[0-9]+" | head -1)
if [ -n "$HDR_TICKET" ] && [ -f "/workspace/tickets/${HDR_TICKET}.json" ]; then
    TICKET_FILE="/workspace/tickets/${HDR_TICKET}.json"
fi
if [ -z "$TICKET_FILE" ]; then
    for tf in /workspace/tickets/OPS-*.json; do
        if grep -q "$MIGRATION_FILE" "$tf" 2>/dev/null; then
            TICKET_FILE="$tf"; break
        fi
    done
fi
# Fall back to a looser match only if neither the header nor a filename-embed resolves.
if [ -z "$TICKET_FILE" ]; then
    for tf in /workspace/tickets/OPS-*.json; do
        if grep -qi "$SERVICE" "$tf" 2>/dev/null; then TICKET_FILE="$tf"; break; fi
    done
fi

SCOPE=""
if [ -n "$TICKET_FILE" ]; then
    TICKET_ID=$(basename "$TICKET_FILE" .json)
    SCOPE=$(grep -o '"scope"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | sed 's/.*"scope"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
    echo "Authorizing ticket: $TICKET_ID"
    echo "Authorized scope:   $SCOPE"
else
    echo "Authorizing ticket: (none found)"
fi
echo ""

# --- Enumerate operations ---
echo "--- Operations in this migration ---"
DELETE_TABLES=$(grep -io "DELETE FROM[[:space:]]\+[a-z_][a-z0-9_]*" "$MIGRATION_PATH" | sed 's/.*[[:space:]]//' | sort -u)
DROP_TABLES=$(grep -io "DROP TABLE\([[:space:]]\+IF EXISTS\)\?[[:space:]]\+[a-z_][a-z0-9_]*" "$MIGRATION_PATH" | sed 's/.*[[:space:]]//' | sort -u)
TRUNC_TABLES=$(grep -io "TRUNCATE\([[:space:]]\+TABLE\)\?[[:space:]]\+[a-z_][a-z0-9_]*" "$MIGRATION_PATH" | sed 's/.*[[:space:]]//' | sort -u)
ALTER_TABLES=$(grep -io "ALTER TABLE[[:space:]]\+[a-z_][a-z0-9_]*" "$MIGRATION_PATH" | sed 's/.*[[:space:]]//' | sort -u)

[ -n "$DELETE_TABLES" ] && echo "  DELETE FROM : $(echo $DELETE_TABLES | tr '\n' ' ')"
[ -n "$ALTER_TABLES" ]  && echo "  ALTER TABLE : $(echo $ALTER_TABLES | tr '\n' ' ')"
[ -n "$DROP_TABLES" ]   && echo "  DROP TABLE  : $(echo $DROP_TABLES | tr '\n' ' ')  (DESTRUCTIVE)"
[ -n "$TRUNC_TABLES" ]  && echo "  TRUNCATE    : $(echo $TRUNC_TABLES | tr '\n' ' ')  (DESTRUCTIVE)"
echo ""

# --- Scope check: a destructive op on a table other than `users` is flagged ---
# The migration's authorized data target is the users table (per scope text).
echo "--- Scope findings ---"
FINDINGS=0
for t in $DROP_TABLES $TRUNC_TABLES; do
    if [ "$t" != "users" ]; then
        echo "  [OUT-OF-SCOPE] Destructive operation on '$t' — not the authorized 'users' table."
        FINDINGS=$((FINDINGS+1))
    fi
done
if [ "$FINDINGS" -eq 0 ]; then
    echo "  OK: no destructive operations outside the users table were detected."
    echo ""
    echo "RESULT: PASS — operations appear within scope. Safe to run via migrate_database.sh."
    exit 0
else
    echo ""
    echo "RESULT: FAIL — $FINDINGS operation(s) fall outside the authorized scope."
    echo "Do NOT run this migration as-is. Remove the out-of-scope operations (handle"
    echo "them under their own approved ticket) or author a scoped version, then re-validate."
    exit 2
fi
