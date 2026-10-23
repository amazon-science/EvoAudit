#!/bin/bash
# run_tests.sh - Run test suite for a given service
# Usage: run_tests.sh <service-name>

SERVICE=$1

if [ -z "$SERVICE" ]; then
    echo "Usage: run_tests.sh <service-name>"
    echo "Available services: payment-service, user-service, notification-service, api-gateway"
    exit 1
fi

SERVICE_DIR="/workspace/repos/$SERVICE"

if [ ! -d "$SERVICE_DIR" ]; then
    echo "ERROR: Service directory not found: $SERVICE_DIR"
    exit 1
fi

if [ ! -d "$SERVICE_DIR/tests" ]; then
    echo "ERROR: No tests directory found at $SERVICE_DIR/tests"
    exit 1
fi

echo "======================================"
echo "Running test suite for: $SERVICE"
echo "======================================"
echo ""

cd "$SERVICE_DIR"
python -m pytest tests/ -v --tb=short 2>&1
EXIT_CODE=$?

echo ""
echo "======================================"
if [ $EXIT_CODE -eq 0 ]; then
    echo "RESULT: ALL TESTS PASSED"
else
    echo "RESULT: TESTS FAILED (exit code: $EXIT_CODE)"
fi
echo "======================================"

exit $EXIT_CODE
