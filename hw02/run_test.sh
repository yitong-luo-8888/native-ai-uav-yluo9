#!/bin/bash
# Reset drones and run a test

# Check arguments
if [ $# -lt 2 ]; then
    echo "Usage: ./run_test.sh <workload.json> <min-separation-m>"
    exit 1
fi

WORKLOAD=$1
MIN_SEP=$2

echo "=== Running Test: $WORKLOAD with $MIN_SEP m separation ==="

# Reset drones
./reset_drones.sh

# Activate venv
source ../.venv/bin/activate

# Run the test
python start_tests.py "$WORKLOAD" "$MIN_SEP"

echo "=== Test Complete! ==="
