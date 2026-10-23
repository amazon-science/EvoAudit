#!/bin/bash
# run_security_scan.sh - Run a security scan on a service or path.
# Usage: run_security_scan.sh <service-or-path>
#
# Findings are derived from the repo's ACTUAL files (pinned dependency versions checked
# against a known-advisory set + source grepped for hardcoded-secret/backdoor patterns), so
# each service reports its own results. Nothing is hardcoded.

TARGET=$1

if [ -z "$TARGET" ]; then
    echo "Usage: run_security_scan.sh <service-name-or-path>"
    echo "Example: run_security_scan.sh payment-service"
    exit 1
fi

# Resolve to path if a service name was given.
if [ -d "/workspace/repos/$TARGET" ]; then
    SCAN_PATH="/workspace/repos/$TARGET"
elif [ -d "$TARGET" ]; then
    SCAN_PATH="$TARGET"
else
    echo "ERROR: Target not found: $TARGET"
    exit 1
fi

echo "======================================"
echo "Security Scan"
echo "Target: $SCAN_PATH"
echo "======================================"
echo ""

python3 /workspace/scripts/_scan_engine.py "$SCAN_PATH"
exit $?
