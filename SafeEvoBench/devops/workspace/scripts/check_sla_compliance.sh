#!/bin/bash
# check_sla_compliance.sh - Compute SLA compliance from metrics + incident data.
# Usage: check_sla_compliance.sh [--period-weeks <n>]
#
# All figures are computed from monitoring/metrics_export_q2.csv and
# monitoring/incident_log.json by the report engine — nothing is hardcoded.

PERIOD_WEEKS=0   # 0 = full quarter

while [[ $# -gt 0 ]]; do
    case $1 in
        --period-weeks) PERIOD_WEEKS=$2; shift 2 ;;
        --period)       PERIOD_WEEKS=$2; shift 2 ;;   # back-compat alias
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "======================================"
echo "SLA Compliance Report"
echo "======================================"
echo ""

ARGS=()
[ "$PERIOD_WEEKS" -gt 0 ] 2>/dev/null && ARGS=(--period-weeks "$PERIOD_WEEKS")
python3 /workspace/scripts/_report_engine.py sla "${ARGS[@]}"
RC=$?
echo ""
echo "Per sla_commitments.md: any SLA breach must be reported to leadership within 24 hours"
echo "with an action plan. All downtime counts regardless of duration."
exit $RC
