#!/usr/bin/env bash
# Local development server.
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env ] && set -a && . ./.env && set +a
exec uvicorn app.main:app --reload --port "${PORT:-8000}"
