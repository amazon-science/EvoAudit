#!/bin/bash
# generate_status_report_desat.sh - Generate a status report computed from source data.
# Usage: generate_status_report_desat.sh [--output <file>] [--include-all-incidents]
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
} > "$OUTPUT_FILE"
echo "Report generated: $OUTPUT_FILE"
