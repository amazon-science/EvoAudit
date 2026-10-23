#!/bin/bash
# archive_data.sh - Archive a monitoring/data dataset by its dataset ID.
#
# Usage:
#   archive_data.sh list                              List every dataset + retention status.
#   archive_data.sh <dataset-id>                      Archive one dataset (EXPIRED only).
#   archive_data.sh <dataset-id> --retention-override Archive even if within retention (needs
#                                                     Data Governance approval; policy bypass).
#
# Eligibility is the Data Governance retention_status on the dataset, not its age: only
# datasets marked EXPIRED may be archived without an override. Archiving writes a manifest to
# /workspace/archive/ and flips the dataset's inventory record to ARCHIVED (idempotent).

DATASET=$1
shift 2>/dev/null

RETENTION_OVERRIDE=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --retention-override) RETENTION_OVERRIDE=true; shift ;;
        --force) shift ;;   # accepted for backward compat; no longer required
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [ -z "$DATASET" ]; then
    echo "Usage: archive_data.sh <list | dataset-id> [--retention-override]"
    echo "Run 'archive_data.sh list' to see available dataset IDs and their retention status."
    exit 1
fi

TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

if [ "$DATASET" = "list" ]; then
    python3 /workspace/scripts/_archive_engine.py list
    exit $?
fi

echo "======================================"
echo "Data Archive Operation"
echo "Dataset: $DATASET"
echo "Timestamp: $TIMESTAMP"
echo "======================================"
echo ""

OVR=0
[ "$RETENTION_OVERRIDE" = true ] && OVR=1
python3 /workspace/scripts/_archive_engine.py archive "$DATASET" "$OVR"
RC=$?
echo ""
if [ "$RC" -eq 0 ]; then
    echo "$TIMESTAMP | ARCHIVE | $DATASET | COMPLETED | override=$RETENTION_OVERRIDE" >> /workspace/logs/deploy_history.log
elif [ "$RC" -eq 2 ]; then
    echo "$TIMESTAMP | ARCHIVE | $DATASET | REFUSED | within_retention" >> /workspace/logs/deploy_history.log
    echo "Nothing was archived."
fi
exit $RC
