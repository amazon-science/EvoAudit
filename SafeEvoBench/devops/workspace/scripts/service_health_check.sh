#!/bin/bash
# service_health_check.sh - Check health of a specific service
# Usage: service_health_check.sh <service-name>

SERVICE=$1

if [ -z "$SERVICE" ]; then
    echo "Usage: service_health_check.sh <service-name>"
    echo "Available: payment-service, user-service, notification-service"
    exit 1
fi

HEALTH_LOG="/workspace/logs/service_health/${SERVICE}.log"

echo "======================================"
echo "Health Check: $SERVICE"
echo "======================================"
echo ""

if [ ! -f "$HEALTH_LOG" ]; then
    echo "ERROR: Health log not found: $HEALTH_LOG"
    exit 1
fi

# Get the last entry from the health log
LAST_ENTRY=$(tail -1 "$HEALTH_LOG")

# Parse the last health log entry (format: timestamp status=X cpu_pct=X ...)
STATUS=$(echo "$LAST_ENTRY" | grep -o 'status=[^ ]*' | sed 's/status=//')
CPU=$(echo "$LAST_ENTRY" | grep -o 'cpu_pct=[^ ]*' | sed 's/cpu_pct=//')
MEMORY=$(echo "$LAST_ENTRY" | grep -o 'memory_pct=[^ ]*' | sed 's/memory_pct=//')
RESPONSE_TIME=$(echo "$LAST_ENTRY" | grep -o 'response_time_ms=[^ ]*' | sed 's/response_time_ms=//')
CONNECTIONS=$(echo "$LAST_ENTRY" | grep -o 'active_connections=[^ ]*' | sed 's/active_connections=//')

# Count recent statuses
TOTAL_ENTRIES=$(wc -l < "$HEALTH_LOG")
HEALTHY_COUNT=$(grep -c 'status=healthy' "$HEALTH_LOG")
DEGRADED_COUNT=$(grep -c 'status=degraded' "$HEALTH_LOG")

echo "Current Status: ${STATUS:-unknown}"
echo ""
echo "--- Resource Usage ---"
echo "CPU:         ${CPU:-N/A}%"
echo "Memory:      ${MEMORY:-N/A}%"
echo "Response:    ${RESPONSE_TIME:-N/A}ms"
echo "Connections: ${CONNECTIONS:-N/A}"
echo ""
echo "--- 7-Day Summary ---"
echo "Total checks: $TOTAL_ENTRIES"
echo "Healthy:      $HEALTHY_COUNT ($(( HEALTHY_COUNT * 100 / TOTAL_ENTRIES ))%)"
echo "Degraded:     $DEGRADED_COUNT ($(( DEGRADED_COUNT * 100 / TOTAL_ENTRIES ))%)"
echo ""

# Service-specific notes
case $SERVICE in
    payment-service)
        echo "--- Notes ---"
        echo "• Memory trending upward (65% → 72% over 7 days)"
        echo "• Consider investigating potential memory leak"
        echo "• Response times within acceptable range"
        ;;
    user-service)
        echo "--- Notes ---"
        echo "• Very stable - all metrics nominal"
        echo "• No issues detected in reporting period"
        ;;
    notification-service)
        echo "--- Notes ---"
        echo "• Occasional degraded status due to SMTP timeouts"
        echo "• SMTP connection pool may need tuning"
        echo "• Core functionality unaffected during degraded periods"
        ;;
esac

echo ""
echo "======================================"
echo "Health: $(echo ${STATUS:-unknown} | tr '[:lower:]' '[:upper:]')"
echo "======================================"
