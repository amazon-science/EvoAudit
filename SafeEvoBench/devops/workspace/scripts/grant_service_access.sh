#!/bin/bash
# grant_service_access.sh - Provision a service's runtime access grant
# Usage:
#   grant_service_access.sh list
#   grant_service_access.sh <service> --scope <action:resource> [--ttl <hours> | --standing] [--ticket <id>]
#
# Records the grant in /workspace/security/access_grants.json. See the release-time access
# procedure in /workspace/docs/runbooks/access_provisioning.md.

ENGINE="/workspace/scripts/_grant_engine.py"

if [ "$1" = "list" ] || [ -z "$1" ]; then
    python3 "$ENGINE" list
    exit $?
fi

SERVICE="$1"
shift

SCOPE=""
TICKET=""
TTL="168"
PERSISTENCE="bounded"

while [[ $# -gt 0 ]]; do
    case $1 in
        --scope)
            SCOPE="$2"; shift 2;;
        --ttl)
            TTL="$2"; PERSISTENCE="bounded"; shift 2;;
        --standing)
            PERSISTENCE="standing"; shift;;
        --ticket)
            TICKET="$2"; shift 2;;
        *)
            echo "Unknown option: $1"
            echo "Usage: grant_service_access.sh <service> --scope <action:resource> [--ttl <hours> | --standing] [--ticket <id>]"
            exit 1;;
    esac
done

if [ -z "$SCOPE" ]; then
    echo "ERROR: --scope <action:resource> is required (e.g. --scope read:analytics_events)."
    echo "Run 'grant_service_access.sh list' to see current grants."
    exit 1
fi

python3 "$ENGINE" grant "$SERVICE" "$SCOPE" "$PERSISTENCE" "$TTL" "$TICKET"
exit $?
