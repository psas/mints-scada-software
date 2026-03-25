#!/usr/bin/env bash
set -euo pipefail

python -m unittest discover -s test_unittest_dev -t . -p "test_*.py" -v
