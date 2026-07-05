upload_code="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

upload_hash="$(python - "$upload_code" <<'PY'
import hashlib
import sys
print(hashlib.sha256(sys.argv[1].encode("utf-8")).hexdigest())
PY
)"

echo "$upload_code"
echo "$upload_hash"