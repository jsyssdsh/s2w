#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="farmflow"

# Stop and remove container, keep volume (idempotent)
docker rm -f "$CONTAINER_NAME" &>/dev/null || true

echo "울퉁불퉁 농장 AI stopped."
