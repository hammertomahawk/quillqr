#!/usr/bin/env bash

source .venv/bin/activate

gunicorn \
  -w 2 \
  -b 127.0.0.1:8000 \
  --access-logfile - \
  --error-logfile - \
  'app:app'
