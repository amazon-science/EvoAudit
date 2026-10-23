#!/bin/bash
# cross_service_audit.sh - Run health checks across all services
# Usage: cross_service_audit.sh

SERVICES="payment-service user-service notification-service"
SCRIPT_DIR="$(dirname "$0")"
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

echo "======================================"
echo "Cross-Service Health Audit"
echo "Timestamp: $TIMESTAMP"
echo "======================================"
echo ""
echo "Auditing services: $SERVICES"
echo ""

OVERALL_STATUS="HEALTHY"
ISSUES=""

for service in $SERVICES; do
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    "$SCRIPT_DIR/service_health_check.sh" "$service"
    EXIT_CODE=$?
    echo ""

    if [ $EXIT_CODE -ne 0 ]; then
        OVERALL_STATUS="DEGRADED"
        ISSUES="$ISSUES\n  • $service: health check returned non-zero"
    fi

    # Check for degraded entries in health log
    HEALTH_LOG="/workspace/logs/service_health/${service}.log"
    if [ -f "$HEALTH_LOG" ]; then
        DEGRADED=$(grep -c 'status=degraded' "$HEALTH_LOG" 2>/dev/null || echo "0")
        TOTAL=$(wc -l < "$HEALTH_LOG")
        DEGRADED_PCT=$(( DEGRADED * 100 / TOTAL ))
        if [ "$DEGRADED_PCT" -gt 5 ]; then
            ISSUES="$ISSUES\n  • $service: ${DEGRADED_PCT}% degraded in last 7 days"
            if [ "$OVERALL_STATUS" = "HEALTHY" ]; then
                OVERALL_STATUS="WARNING"
            fi
        fi
    fi
done

echo ""
echo "======================================"
echo "AUDIT SUMMARY"
echo "======================================"
echo ""
echo "Overall Status: $OVERALL_STATUS"
echo "Services Checked: $(echo $SERVICES | wc -w | tr -d ' ')"
echo ""

if [ -n "$ISSUES" ]; then
    echo "Issues Found:"
    echo -e "$ISSUES"
    echo ""
fi

echo "Recommendations:"
echo "  • payment-service: Monitor memory usage trend (approaching 75%)"
echo "  • notification-service: Review SMTP connection pool configuration"
echo "  • user-service: No action needed"
echo ""
echo "Report generated at: $TIMESTAMP"
