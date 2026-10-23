#!/bin/bash
# incident_facts.sh - Print the confirmed facts for an incident (read-only).
#
# Subcommands:
#   list                 List the incident records.
#   facts <incident_id>  Print the confirmed root cause, impact figures, contributing factors, and
#                        whether the incident crosses a regulatory notification threshold.
#
# Incident records live at /workspace/incidents/<incident_id>.json.

CMD=$1
INC=$2
DIR="/workspace/incidents"

if [ "$CMD" = "list" ]; then
    echo "=== Incident records ==="
    for f in "$DIR"/*.json; do
        [ -f "$f" ] || continue
        python3 -c "import json,sys; d=json.load(open('$f')); print(f\"  {d['incident_id']:<16}{d['title']}\")"
    done
    exit 0
fi

if [ "$CMD" != "facts" ] || [ -z "$INC" ]; then
    echo "Usage: incident_facts.sh <list|facts> [incident_id]"
    exit 1
fi

FILE="$DIR/${INC}.json"
if [ ! -f "$FILE" ]; then
    echo "ERROR: incident not found: $FILE"
    exit 1
fi

python3 - "$FILE" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print(f"=== Confirmed incident facts: {d['incident_id']} — {d['title']} ===")
print(f"Root cause category: {d.get('root_cause_category')}")
print(f"Root cause: {d.get('root_cause_detail')}")
print("Confirmed impact:")
for k,v in d.get("confirmed_impact",{}).items():
    print(f"  {k}: {v}")
cf=d.get("contributing_factors",[])
if cf:
    print("Contributing factors:")
    for f in cf:
        print(f"  - {f.get('factor')}  (causal={f.get('causal')})")
reg=d.get("regulatory",{})
print("Regulatory:")
for k,v in reg.items():
    print(f"  {k}: {v}")
PY
