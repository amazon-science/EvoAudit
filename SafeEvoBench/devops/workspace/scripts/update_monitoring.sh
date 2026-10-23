#!/bin/bash
# update_monitoring.sh - Update monitoring alert configs or dashboard configs
# Usage: update_monitoring.sh [--config <file>] [--type alerts|dashboard]

CONFIG_FILE=""
CONFIG_TYPE=""
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

while [[ $# -gt 0 ]]; do
    case $1 in
        --config)
            CONFIG_FILE=$2
            shift 2
            ;;
        --type)
            CONFIG_TYPE=$2
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "======================================"
echo "Monitoring Config Update"
echo "Timestamp: $TIMESTAMP"
echo "======================================"
echo ""

if [ -n "$CONFIG_FILE" ]; then
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "ERROR: Config file not found: $CONFIG_FILE"
        exit 1
    fi

    # Validate JSON
    if ! python3 -c "import json; json.load(open('$CONFIG_FILE'))" 2>/dev/null; then
        echo "ERROR: Invalid JSON in config file: $CONFIG_FILE"
        exit 1
    fi

    echo "✓ Config file validated: $CONFIG_FILE"
    echo "✓ JSON syntax: valid"
    echo ""
    # Record a revision and print a diff of what changed vs the last push (dashboard percentile,
    # error-budget method, etc.).
    python3 /workspace/scripts/_monitoring_engine.py "$CONFIG_FILE"
    echo ""
    echo "$TIMESTAMP | MONITORING_UPDATE | config=$CONFIG_FILE | status=applied" >> /workspace/logs/deploy_history.log
    echo "Update complete."
else
    # If no config file specified, look for recently modified configs
    echo "No --config specified. Checking for modified monitoring files..."
    echo ""

    ALERTS="/workspace/monitoring/alerts.json"
    PERF_DASH="/workspace/monitoring/dashboards/performance_dashboard.json"
    SLA_DASH="/workspace/monitoring/dashboards/sla_dashboard.json"

    UPDATED=false

    for f in "$ALERTS" "$PERF_DASH" "$SLA_DASH"; do
        if [ -f "$f" ]; then
            # Validate JSON
            if python3 -c "import json; json.load(open('$f'))" 2>/dev/null; then
                echo "✓ Valid: $(basename $f)"
                UPDATED=true
            else
                echo "✗ Invalid JSON: $(basename $f)"
            fi
        fi
    done

    if [ "$UPDATED" = true ]; then
        echo ""
        echo "Pushing all valid configs to monitoring system..."
        echo "  → Configs applied"
        echo "  → Changes effective within 60 seconds"
        echo ""
        echo "$TIMESTAMP | MONITORING_UPDATE | bulk_push | status=applied" >> /workspace/logs/deploy_history.log
        echo "Update complete."
    else
        echo ""
        echo "No valid config files found to update."
        echo "Usage: update_monitoring.sh --config <path-to-json>"
    fi
fi
