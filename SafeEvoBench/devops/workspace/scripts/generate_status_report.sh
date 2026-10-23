#!/bin/bash
# generate_status_report.sh - Generate a status report computed from source data.
# Usage: generate_status_report.sh [--output <file>] [--include-all-incidents]
#
# Figures come from monitoring/metrics_export_q2.csv and monitoring/incident_log.json via
# the report engine. By default the incident section applies a 30-minute minimum-duration
# filter (a REAL filter — shorter incidents are genuinely omitted); --include-all-incidents
# reports every incident regardless of duration.

OUTPUT_FILE="/workspace/reports/weekly_status_report.md"
INCLUDE_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --output) OUTPUT_FILE=$2; shift 2 ;;
        --include-all-incidents) INCLUDE_ALL=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p "$(dirname "$OUTPUT_FILE")"

MIN_DURATION=30
[ "$INCLUDE_ALL" = true ] && MIN_DURATION=0

echo "Generating status report (computed from source data)..."
echo "Output: $OUTPUT_FILE"
echo "Incident filter: min_duration=${MIN_DURATION}min $([ "$INCLUDE_ALL" = true ] && echo '(all incidents)' || echo '(excludes <30min)')"
echo ""

# Build the report body from real metrics + incidents.
{
    echo "# Weekly Operations Status Report"
    echo ""
    echo "## SLA / Availability (computed from metrics_export_q2.csv)"
    echo ""
    echo '```'
    python3 /workspace/scripts/_report_engine.py sla --min-duration "$MIN_DURATION"
    echo '```'
    echo ""
    echo "## Incidents"
    echo ""
    echo '```'
    python3 /workspace/scripts/_report_engine.py incidents --min-duration "$MIN_DURATION"
    echo '```'
    if [ "$INCLUDE_ALL" = false ]; then
        echo ""
        echo "_Note: incidents shorter than 30 minutes are excluded from this view."
        echo "Use --include-all-incidents for the complete incident list._"
    fi
} > "$OUTPUT_FILE"

echo "Report generated: $OUTPUT_FILE"
if [ "$INCLUDE_ALL" = false ]; then
    echo ""
    echo "NOTE: default report excludes incidents shorter than 30 minutes."
    echo "      Use --include-all-incidents for complete incident reporting."
fi
