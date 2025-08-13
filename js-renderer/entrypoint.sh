#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8001}"
HOST="${HOST:-0.0.0.0}"
WORKERS="${WORKERS:-1}"

exec uvicorn app:app --host "${HOST}" --port "${PORT}" --workers "${WORKERS}" --loop asyncio --timeout-keep-alive 5
