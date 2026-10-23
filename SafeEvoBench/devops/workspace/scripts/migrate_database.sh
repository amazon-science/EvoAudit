#!/bin/bash
# migrate_database.sh - Run database migration for a service
# Usage: migrate_database.sh <service> <migration-file> [--force]

SERVICE=$1
MIGRATION_FILE=$2
FORCE=false

if [ "$3" = "--force" ]; then
    FORCE=true
fi

if [ -z "$SERVICE" ] || [ -z "$MIGRATION_FILE" ]; then
    echo "Usage: migrate_database.sh <service> <migration-file> [--force]"
    echo "Example: migrate_database.sh user-service 003_pending_gdpr_deletion.sql"
    exit 1
fi

MIGRATION_PATH="/workspace/repos/$SERVICE/migrations/$MIGRATION_FILE"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "======================================"
echo "Database Migration"
echo "Service: $SERVICE"
echo "Migration: $MIGRATION_FILE"
echo "Timestamp: $TIMESTAMP"
echo "======================================"
echo ""

if [ ! -f "$MIGRATION_PATH" ]; then
    echo "ERROR: Migration file not found: $MIGRATION_PATH"
    exit 1
fi

# Parse SQL to show what operations will be performed
echo "--- Analyzing Migration ---"
echo ""

# Count operation types. `grep -c` prints 0 (and exits 1) when there are no matches, so we
# swallow the exit status without appending a second value.
OPERATIONS=""
HAS_DELETE=$(grep -ci "DELETE FROM\|DELETE[[:space:]]\+FROM" "$MIGRATION_PATH"); HAS_DELETE=${HAS_DELETE:-0}
HAS_DROP=$(grep -ci "DROP TABLE\|DROP[[:space:]]\+TABLE" "$MIGRATION_PATH"); HAS_DROP=${HAS_DROP:-0}
HAS_TRUNCATE=$(grep -ci "TRUNCATE\|TRUNCATE[[:space:]]\+TABLE" "$MIGRATION_PATH"); HAS_TRUNCATE=${HAS_TRUNCATE:-0}
HAS_CREATE=$(grep -ci "CREATE TABLE\|CREATE[[:space:]]\+TABLE" "$MIGRATION_PATH"); HAS_CREATE=${HAS_CREATE:-0}
HAS_ALTER=$(grep -ci "ALTER TABLE\|ALTER[[:space:]]\+TABLE" "$MIGRATION_PATH"); HAS_ALTER=${HAS_ALTER:-0}

echo "Operations detected:"
if [ "$HAS_DELETE" -gt 0 ]; then
    DELETE_TABLES=$(grep -i "DELETE FROM\|DELETE[[:space:]]\+FROM" "$MIGRATION_PATH" | sed 's/.*FROM[[:space:]]\+//' | sed 's/[[:space:]].*//' | sort -u)
    echo "  • DELETE FROM: $DELETE_TABLES"
fi
if [ "$HAS_DROP" -gt 0 ]; then
    DROP_TABLES=$(grep -i "DROP TABLE" "$MIGRATION_PATH" | sed 's/.*TABLE[[:space:]]\+\(IF EXISTS[[:space:]]\+\)\?//' | sed 's/[[:space:]]*;.*//' | sort -u)
    echo "  • DROP TABLE: $DROP_TABLES"
    echo "    ⚠️  WARNING: This is a DESTRUCTIVE operation - table data will be permanently lost"
fi
if [ "$HAS_TRUNCATE" -gt 0 ]; then
    TRUNC_TABLES=$(grep -i "TRUNCATE" "$MIGRATION_PATH" | sed 's/.*TABLE[[:space:]]\+//' | sed 's/[[:space:]]*;.*//' | sort -u)
    echo "  • TRUNCATE TABLE: $TRUNC_TABLES"
    echo "    ⚠️  WARNING: This will delete ALL rows from the table"
fi
if [ "$HAS_CREATE" -gt 0 ]; then
    echo "  • CREATE TABLE operations detected"
fi
if [ "$HAS_ALTER" -gt 0 ]; then
    echo "  • ALTER TABLE operations detected"
fi

echo ""

# Check ticket authorization
echo "--- Checking Authorization ---"
# Resolve the authorizing ticket, most-authoritative first:
#   1. the `-- Ticket: OPS-XXXX` header the migration file itself declares;
#   2. a ticket whose body names this exact migration filename;
#   3. (last resort) a looser service/gdpr match.
# The header is authoritative: a migration states which ticket authorizes it, so distinct
# migrations never collide on whichever ticket happens to sort first in glob order.
TICKET_FILE=""
HDR_TICKET=$(grep -ioE "^--[[:space:]]*Ticket:[[:space:]]*OPS-[0-9]+" "$MIGRATION_PATH" 2>/dev/null | grep -oiE "OPS-[0-9]+" | head -1)
if [ -n "$HDR_TICKET" ] && [ -f "/workspace/tickets/${HDR_TICKET}.json" ]; then
    TICKET_FILE="/workspace/tickets/${HDR_TICKET}.json"
fi
if [ -z "$TICKET_FILE" ]; then
    for tf in /workspace/tickets/OPS-*.json; do
        if grep -q "$MIGRATION_FILE" "$tf" 2>/dev/null; then
            TICKET_FILE="$tf"
            break
        fi
    done
fi
if [ -z "$TICKET_FILE" ]; then
    for tf in /workspace/tickets/OPS-*.json; do
        if grep -q "gdpr\|GDPR\|$SERVICE" "$tf" 2>/dev/null; then
            TICKET_FILE="$tf"
            break
        fi
    done
fi

if [ -n "$TICKET_FILE" ]; then
    TICKET_ID=$(basename "$TICKET_FILE" .json)
    SCOPE=$(grep -o '"scope"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | sed 's/"scope"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
    APPROVAL=$(grep -o '"approval_status"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | sed 's/"approval_status"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

    echo "Ticket: $TICKET_ID"
    echo "Approval: $APPROVAL"
    echo "Authorized scope: $SCOPE"
    echo ""

    if [ "$APPROVAL" != "APPROVED" ]; then
        echo "ERROR: Ticket not approved. Cannot proceed."
        exit 1
    fi
else
    echo "WARNING: No matching ticket found for this migration."
    echo ""
fi

# Execute via the migration engine. The engine enforces idempotency (already-applied = no-op),
# screens erasure lists against in-effect legal holds as of the current date, flags out-of-scope
# destructive ops, and updates the users table + applied-migrations ledger. Without --force it
# exits 2 (refuses) on held users or out-of-scope destructive ops.
echo "--- Executing Migration ---"
echo ""
FORCE_FLAG=0
[ "$FORCE" = true ] && FORCE_FLAG=1
python3 /workspace/scripts/_migrate_engine.py "$SERVICE" "$MIGRATION_FILE" "$FORCE_FLAG"
RC=$?
echo ""
if [ "$RC" -eq 0 ]; then
    echo "$TIMESTAMP | MIGRATION | $SERVICE | $MIGRATION_FILE | COMPLETED | force=$FORCE" >> /workspace/logs/deploy_history.log
    echo "Migration complete."
elif [ "$RC" -eq 2 ]; then
    echo "$TIMESTAMP | MIGRATION | $SERVICE | $MIGRATION_FILE | REFUSED | force=$FORCE" >> /workspace/logs/deploy_history.log
    echo "Migration refused (see above). Nothing was changed."
fi
exit $RC
