#!/bin/bash
# Helper script to run the automated test suite

# Ensure we are in the project root
cd "$(dirname "$0")/.."

# Install/Update project and testing dependencies
python3 -m pip install -r requirements.txt

# Run tests with a 30-second global timeout and coverage report
echo "--- Running Unit & Integration Tests with Coverage ---"
export PYTHONPATH=$PYTHONPATH:$(pwd)/src:$(pwd)/utils
python3 -m pytest tests/ -v --timeout=30 --cov=src --cov=utils --cov-report=term-missing
