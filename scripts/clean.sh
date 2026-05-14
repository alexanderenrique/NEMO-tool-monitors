#!/bin/bash
# Remove build artifacts.
set -e
DEV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DEV_DIR"
rm -rf build/ dist/ ./*.egg-info
echo "Cleaned build/, dist/, *.egg-info"
