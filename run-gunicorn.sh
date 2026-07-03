#!/usr/bin/env bash

set -euo pipefail

cd "$(dirname "$0")"

source .venv/bin/activate

: "${QUILLQR_PUBLIC_BASE_URL:?Set QUILLQR_PUBLIC_BASE_URL, e.g. https://quillqr.example.com}"

exec gunicorn \
  -w 1 \
  --threads 2 \
  -b 127.0.0.1:8000 \
  --access-logfile - \
  --error-logfile - \
  'app:app'