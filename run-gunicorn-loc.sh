#!/usr/bin/env bash

set -euo pipefail;

env \
  QUILLQR_PUBLIC_BASE_URL="http://localhost:8080" \
  QUILLQR_ENABLE_PDF_UPLOADS=1 \
  QUILLQR_PDF_UPLOAD_CODE_HASH="034ea4e94cee74efae23dca945d94976c040ac9670d5e087ef8d02c9751059fb" \
  QUILLQR_PDF_SANITIZER_COMMAND="gs" \
  QUILLQR_REQUIRE_SELECTABLE_TEXT=1 \
  QUILLQR_MIN_PDF_TEXT_PAGE_PERCENT=60 \
  QUILLQR_PDF_TEXT_PAGE_MIN_CHARS=1 \
  QUILLQR_PDF_AV_SCAN_COMMAND="clamscan" \
  QUILLQR_REQUIRE_PDF_AV_SCAN=1 \
  PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/gunicorn \
    --no-control-socket \
    -w 1 \
    --threads 2 \
    -b 127.0.0.1:8000 \
    --access-logfile - \
    --error-logfile - \
    app:app
