#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${RSHELPER_PYTHON:-$REPO_DIR/.venv/bin/python}" "$REPO_DIR/scripts/sync-and-push-state.py" --copy-only
