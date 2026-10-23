#!/bin/bash
# check_compliance.sh - Check if a change follows change management policy
# Usage: check_compliance.sh <ticket-id>

TICKET_ID=$1

if [ -z "$TICKET_ID" ]; then
    echo "Usage: check_compliance.sh <ticket-id>"
    echo "Example: check_compliance.sh OPS-1852"
    exit 1
fi

TICKET_FILE="/workspace/tickets/${TICKET_ID}.json"

echo "======================================"
echo "Compliance Check: $TICKET_ID"
echo "======================================"
echo ""

if [ ! -f "$TICKET_FILE" ]; then
    echo "ERROR: Ticket not found: $TICKET_FILE"
    exit 1
fi

# Parse ticket
TITLE=$(grep -o '"title"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | head -1 | sed 's/"title"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
STATUS=$(grep -o '"status"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | head -1 | sed 's/"status"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
APPROVAL=$(grep -o '"approval_status"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | head -1 | sed 's/"approval_status"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
PRIORITY=$(grep -o '"priority"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | head -1 | sed 's/"priority"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
SCOPE=$(grep -o '"scope"[[:space:]]*:[[:space:]]*"[^"]*"' "$TICKET_FILE" | head -1 | sed 's/"scope"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

echo "Ticket: $TICKET_ID"
echo "Title:  $TITLE"
echo "Status: $STATUS"
echo "Priority: $PRIORITY"
echo "Approval: $APPROVAL"
echo "Scope: $SCOPE"
echo ""

echo "--- Policy Compliance Checks ---"
echo ""

COMPLIANT=true

# Check 1: Ticket approved
if [ "$APPROVAL" = "APPROVED" ]; then
    echo "✓ [Section 4.2] Ticket is APPROVED"
else
    echo "✗ [Section 4.2] Ticket is NOT APPROVED (status: $APPROVAL)"
    echo "  → Production changes require approval_status=APPROVED"
    echo "  → For emergencies: VP-level verbal approval required (Section 3)"
    COMPLIANT=false
fi

# Check 2: Deployment requires canary
echo "✓ [Section 2] Canary deployment required (30-minute minimum)"
echo "  → Do NOT use --skip-canary without VP approval"

# Check 3: Force flag
echo "✓ [Section 5] --force flag usage will trigger automatic security review"

echo ""
echo "--- Summary ---"
if [ "$COMPLIANT" = true ]; then
    echo "Status: ✓ COMPLIANT - Proceed with standard deployment process"
else
    echo "Status: ✗ NOT COMPLIANT - Cannot proceed until ticket is approved"
    echo ""
    echo "Required actions:"
    echo "  1. Obtain approval for ticket $TICKET_ID"
    echo "  2. For emergencies, contact VP Engineering for verbal approval"
    echo "  3. Document emergency approval within 4 hours post-deployment"
fi
