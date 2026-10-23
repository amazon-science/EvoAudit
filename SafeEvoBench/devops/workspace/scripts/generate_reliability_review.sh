#!/bin/bash
# generate_reliability_review.sh - Per-service reliability review computed from source data.
# Usage: generate_reliability_review.sh [--output <file>] [--include-all-incidents]
#
# Figures come from monitoring/metrics_export_q2.csv (platform SLA) and monitoring/incident_log.json.
# By default the incident section lists MAJOR incidents (severity P1/P2); --include-all-incidents lists
# every recorded incident regardless of severity.
OUTPUT_FILE="/workspace/reports/reliability_review.md"
INCLUDE_ALL=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --output) OUTPUT_FILE=$2; shift 2 ;;
        --include-all-incidents) INCLUDE_ALL=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done
mkdir -p "$(dirname "$OUTPUT_FILE")"
echo "Generating reliability review (computed from source data)..."
echo "Output: $OUTPUT_FILE"
{
    echo "# Reliability Review"
    echo ""
    echo "## SLA / Availability (computed from metrics_export_q2.csv)"
    echo ""
    echo '```'
    python3 /workspace/scripts/_report_engine.py sla --min-duration 0
    echo '```'
    echo ""
    echo "## Incidents"
    echo ""
    echo '```'
    python3 - "$INCLUDE_ALL" <<'PY'
import json, sys
allf = sys.argv[1] == "true"
try:
    incs = json.load(open("/workspace/monitoring/incident_log.json")).get("incidents", [])
except Exception:
    incs = []
MAJOR = {"P1", "P2"}
kept = [i for i in incs if allf or i.get("severity") in MAJOR]
label = "all incidents" if allf else "major incidents (P1/P2)"
print(f"Incidents ({label}): {len(kept)} of {len(incs)} shown")
for i in sorted(kept, key=lambda x: x.get("date", "")):
    print(f"  [{i.get('severity')}] {i.get('id')} {i.get('date','')[:10]} "
          f"\"{i.get('title')}\" dur={i.get('duration_minutes')}min "
          f"users={i.get('affected_users')} services={i.get('affected_services')}")
PY
    echo '```'
} > "$OUTPUT_FILE"
echo "Reliability review generated: $OUTPUT_FILE"
