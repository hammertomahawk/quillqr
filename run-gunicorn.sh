#!/usr/bin/env bash

sudo -u "$APP_USER" env \
  QUILLQR_PUBLIC_BASE_URL="http://localhost:8080" \
  QUILLQR_ENABLE_PDF_UPLOADS=0 \
  QUILLQR_PDF_UPLOAD_CODE="<MAKE_SECURE_CODE>" \
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
