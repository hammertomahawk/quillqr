from __future__ import annotations

from dataclasses import dataclass
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename

import hashlib
import os
import re
import secrets
import shlex
import shutil
import string
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
    url_for,
)

from db import close_db, execute, init_db, query_one


APP_NAME = "QuillQR"
DEFAULT_EXPIRATION_DAYS = 90

MAX_CONTENT_BYTES = 50 * 1024
MAX_TITLE_CHARS = 120
MAX_PDF_BYTES = int(
    os.environ.get(
        "QUILLQR_MAX_PDF_BYTES",
        str(50 * 1024 * 1024),
    )
)
MAX_PDF_PAGES = int(os.environ.get("QUILLQR_MAX_PDF_PAGES", "100"))
# This check is only meant to reject image-only/scanned PDFs.
# It is percentage-based so tiny real-text PDFs can pass while
# mostly image-only/scanned PDFs fail. A page counts as a text
# page when extracted compact text reaches this small floor.
PDF_TEXT_PAGE_MIN_CHARS = int(
    os.environ.get(
        "QUILLQR_PDF_TEXT_PAGE_MIN_CHARS",
        os.environ.get("QUILLQR_MIN_PDF_TEXT_CHARS", "1"),
    )
)
MIN_PDF_TEXT_PAGE_PERCENT = float(
    os.environ.get("QUILLQR_MIN_PDF_TEXT_PAGE_PERCENT", "60")
)
PDF_PROCESS_TIMEOUT_SECONDS = int(
    os.environ.get("QUILLQR_PDF_PROCESS_TIMEOUT_SECONDS", "90")
)

ALLOWED_FORMATS = {"text", "markdown"}
ALLOWED_PDF_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/octet-stream",
    "",
}

SLUG_ALPHABET = (
    string.ascii_lowercase
    + string.ascii_uppercase
    + string.digits
)

STORED_PDF_RE = re.compile(r"^[A-Za-z0-9]{32}\.pdf$")

FORBIDDEN_PDF_FEATURES = {
    b"/AA": "additional PDF actions",
    b"/AcroForm": "fillable PDF forms",
    b"/EmbeddedFile": "embedded files",
    b"/Filespec": "file attachments or external files",
    b"/GoToR": "remote document actions",
    b"/ImportData": "form import actions",
    b"/JavaScript": "PDF JavaScript",
    b"/JS": "PDF JavaScript",
    b"/Launch": "launch actions",
    b"/Movie": "multimedia content",
    b"/OpenAction": "document open actions",
    b"/RichMedia": "rich media content",
    b"/Sound": "multimedia content",
    b"/SubmitForm": "form submission actions",
    b"/XFA": "XFA forms",
}


PDF_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS pdf_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  read_slug TEXT NOT NULL UNIQUE,
  edit_token_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  stored_filename TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  sanitized_at TEXT,
  pdf_sha256 TEXT,
  page_count INTEGER NOT NULL DEFAULT 0,
  text_char_count INTEGER NOT NULL DEFAULT 0,
  text_page_count INTEGER NOT NULL DEFAULT 0,
  text_page_percent REAL NOT NULL DEFAULT 0,
  safety_status TEXT NOT NULL DEFAULT 'unverified',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  edit_accessed_at TEXT,
  expires_at TEXT NOT NULL,
  deleted_at TEXT
);
"""

PDF_EXTRA_COLUMNS = {
    "sanitized_at": "TEXT",
    "pdf_sha256": "TEXT",
    "page_count": "INTEGER NOT NULL DEFAULT 0",
    "text_char_count": "INTEGER NOT NULL DEFAULT 0",
    "text_page_count": "INTEGER NOT NULL DEFAULT 0",
    "text_page_percent": "REAL NOT NULL DEFAULT 0",
    "safety_status": "TEXT NOT NULL DEFAULT 'unverified'",
}


@dataclass(frozen=True)
class PdfProcessingResult:
    stored_filename: str
    original_filename: str
    file_size_bytes: int
    sanitized_at: str
    pdf_sha256: str
    page_count: int
    text_char_count: int
    text_page_count: int
    text_page_percent: float
    safety_status: str


class PdfUploadRejected(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        extra: dict | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.extra = extra or {}


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    pdf_uploads_enabled = (
        os.environ.get("QUILLQR_ENABLE_PDF_UPLOADS") == "1"
    )
    allow_unsanitized_pdfs = (
        os.environ.get("QUILLQR_ALLOW_UNSANITIZED_PDFS") == "1"
    )
    require_selectable_text = (
        os.environ.get("QUILLQR_REQUIRE_SELECTABLE_TEXT", "1") != "0"
    )
    require_av_scan = (
        os.environ.get(
            "QUILLQR_REQUIRE_PDF_AV_SCAN",
            os.environ.get("QUILLQR_REQUIRE_AV_SCAN", "0"),
        ) == "1"
    )

    sanitizer_command = os.environ.get(
        "QUILLQR_PDF_SANITIZER_COMMAND",
        "gs",
    )
    sanitizer_path = shutil.which(sanitizer_command)

    av_scan_command = (
        os.environ.get("QUILLQR_PDF_AV_SCAN_COMMAND")
        or os.environ.get("QUILLQR_AV_SCAN_COMMAND", "")
    )
    av_scan_parts = shlex.split(av_scan_command)
    av_scan_path = (
        shutil.which(av_scan_parts[0])
        if av_scan_parts
        else None
    )

    app.config.from_mapping(
        DATABASE=str(instance_path / "quillqr.sqlite3"),
        PDF_UPLOAD_DIR=str(instance_path / "pdf_uploads"),
        PDF_PROCESSING_DIR=str(instance_path / "pdf_processing"),
        PDF_UPLOADS_ENABLED=pdf_uploads_enabled,
        PDF_UPLOAD_CODE=os.environ.get("QUILLQR_PDF_UPLOAD_CODE", ""),
        PDF_UPLOAD_CODE_HASH=os.environ.get(
            "QUILLQR_PDF_UPLOAD_CODE_HASH",
            "",
        ),
        PDF_ALLOW_UNSANITIZED=allow_unsanitized_pdfs,
        PDF_REQUIRE_SELECTABLE_TEXT=require_selectable_text,
        PDF_SANITIZER_COMMAND=sanitizer_command,
        PDF_SANITIZER_PATH=sanitizer_path,
        PDF_REQUIRE_AV_SCAN=require_av_scan,
        PDF_AV_SCAN_COMMAND=av_scan_command,
        PDF_AV_SCAN_PATH=av_scan_path,
        MAX_PDF_BYTES=MAX_PDF_BYTES,
        MAX_PDF_PAGES=MAX_PDF_PAGES,
        PDF_TEXT_PAGE_MIN_CHARS=PDF_TEXT_PAGE_MIN_CHARS,
        MIN_PDF_TEXT_PAGE_PERCENT=MIN_PDF_TEXT_PAGE_PERCENT,
        PDF_PROCESS_TIMEOUT_SECONDS=PDF_PROCESS_TIMEOUT_SECONDS,

        # This limits the full request body.
        # Nginx should also enforce client_max_body_size.
        MAX_CONTENT_LENGTH=get_request_body_limit(pdf_uploads_enabled),
    )

    validate_pdf_runtime_config(app)

    app.teardown_appcontext(close_db)

    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,
        x_proto=1,
        x_host=1,
        x_port=1,
    )

    with app.app_context():
        ensure_pdf_schema()

    register_routes(app)

    return app


def validate_pdf_runtime_config(app: Flask) -> None:
    if not app.config["PDF_UPLOADS_ENABLED"]:
        return

    has_raw_code = bool(app.config["PDF_UPLOAD_CODE"])
    has_hashed_code = bool(app.config["PDF_UPLOAD_CODE_HASH"])

    if not (has_raw_code or has_hashed_code):
        raise RuntimeError(
            "PDF uploads are enabled, but no PDF upload code is set. "
            "Set QUILLQR_PDF_UPLOAD_CODE_HASH for production or "
            "QUILLQR_PDF_UPLOAD_CODE for local testing."
        )

    if app.config["PDF_ALLOW_UNSANITIZED"]:
        return

    if not app.config["PDF_SANITIZER_PATH"]:
        raise RuntimeError(
            "PDF uploads are enabled, but Ghostscript was not found. "
            "Install Ghostscript or set QUILLQR_PDF_SANITIZER_COMMAND. "
            "For local-only testing, set QUILLQR_ALLOW_UNSANITIZED_PDFS=1."
        )

    if app.config["PDF_AV_SCAN_COMMAND"] and not app.config["PDF_AV_SCAN_PATH"]:
        raise RuntimeError(
            "PDF AV scanning command was configured, but the scanner was not "
            "found in PATH. Check QUILLQR_PDF_AV_SCAN_COMMAND or "
            "QUILLQR_AV_SCAN_COMMAND."
        )

    if app.config["PDF_REQUIRE_AV_SCAN"] and not app.config["PDF_AV_SCAN_COMMAND"]:
        raise RuntimeError(
            "PDF AV scanning is required, but no scanner command is set. "
            "Set QUILLQR_PDF_AV_SCAN_COMMAND=clamscan. The legacy alias "
            "QUILLQR_AV_SCAN_COMMAND is also accepted."
        )

    if app.config["PDF_REQUIRE_SELECTABLE_TEXT"]:
        try:
            import pypdf  # noqa: F401
        except ImportError as error:
            raise RuntimeError(
                "PDF selectable-text checks require pypdf. "
                "Install dependencies with: pip install -r requirements.txt."
            ) from error


def get_request_body_limit(pdf_uploads_enabled: bool) -> int:
    if pdf_uploads_enabled:
        return MAX_PDF_BYTES + 1024 * 1024

    return 128 * 1024


def ensure_pdf_schema() -> None:
    execute(PDF_SCHEMA_SQL)

    for column_name, column_definition in PDF_EXTRA_COLUMNS.items():
        existing = query_one(
            """
            SELECT name
            FROM pragma_table_info('pdf_documents')
            WHERE name = ?
            """,
            (column_name,),
        )

        if existing is None:
            execute(
                f"ALTER TABLE pdf_documents "
                f"ADD COLUMN { column_name } { column_definition }"
            )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_db_time(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def from_db_time(value: str) -> datetime:
    return datetime.fromisoformat(value)


def new_expiration() -> str:
    expires_at = now_utc() + timedelta(
        days=DEFAULT_EXPIRATION_DAYS
    )
    return to_db_time(expires_at)


def is_expired(row) -> bool:
    expires_at = from_db_time(row["expires_at"])
    return expires_at <= now_utc()


def random_slug(length: int = 10) -> str:
    return "".join(
        secrets.choice(SLUG_ALPHABET)
        for _ in range(length)
    )


def create_unique_slug() -> str:
    for _ in range(20):
        slug = random_slug()

        existing = query_one(
            "SELECT id FROM documents WHERE read_slug = ?",
            (slug,),
        )

        if existing is None:
            return slug

    raise RuntimeError("Could not create unique slug")


def create_unique_pdf_slug() -> str:
    for _ in range(20):
        slug = random_slug()

        existing = query_one(
            "SELECT id FROM pdf_documents WHERE read_slug = ?",
            (slug,),
        )

        if existing is None:
            return slug

    raise RuntimeError("Could not create unique PDF slug")


def create_edit_token() -> str:
    return secrets.token_urlsafe(32)


def hash_edit_token(token: str) -> str:
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def validate_content(
    title: str,
    content: str,
    content_format: str,
) -> tuple[str, str, str]:
    title = title.strip()
    content_format = content_format.strip().lower()

    if content_format not in ALLOWED_FORMATS:
        abort_json(
            400,
            "content_format must be text or markdown",
        )

    if len(title) > MAX_TITLE_CHARS:
        abort_json(
            400,
            f"title must be { MAX_TITLE_CHARS } "
            "characters or fewer",
        )

    content_bytes = len(content.encode("utf-8"))

    if content_bytes == 0:
        abort_json(400, "content is required")

    if content_bytes > MAX_CONTENT_BYTES:
        abort_json(
            400,
            "content is too large",
            {
                "content_bytes": content_bytes,
                "max_content_bytes": MAX_CONTENT_BYTES,
            },
        )

    return title, content, content_format


def abort_json(
    status_code: int,
    message: str,
    extra: dict | None = None,
):
    payload = {
        "ok": False,
        "error": message,
    }

    if extra:
        payload.update(extra)

    response = jsonify(payload)
    response.status_code = status_code
    abort(response)


def get_json_body() -> dict:
    body = request.get_json(silent=True)

    if not isinstance(body, dict):
        abort_json(400, "JSON body required")

    return body


def get_public_base_url() -> str | None:
    value = os.environ.get("QUILLQR_PUBLIC_BASE_URL")

    if not value:
        return None

    return value.rstrip("/")


def build_public_url(path: str) -> str:
    base_url = get_public_base_url()

    if base_url is not None:
        return f"{ base_url }{ path }"

    return url_for(
        "index",
        _external=True,
    ).rstrip("/") + path


def public_document_url(read_slug: str) -> str:
    path = url_for(
        "view_document",
        read_slug=read_slug,
    )

    return build_public_url(path)


def edit_document_url(edit_token: str) -> str:
    path = url_for(
        "edit_document",
        edit_token=edit_token,
    )

    return build_public_url(path)


def public_pdf_document_url(read_slug: str) -> str:
    path = url_for(
        "view_pdf_document",
        read_slug=read_slug,
    )

    return build_public_url(path)


def edit_pdf_document_url(edit_token: str) -> str:
    path = url_for(
        "edit_pdf_document",
        edit_token=edit_token,
    )

    return build_public_url(path)


def pdf_file_url(read_slug: str) -> str:
    path = url_for(
        "serve_pdf_file",
        read_slug=read_slug,
    )

    return build_public_url(path)


def versioned_pdf_file_url(row) -> str:
    return f"{ pdf_file_url(row['read_slug']) }?v={ row['updated_at'] }"


def renew_document_by_id(document_id: int) -> None:
    execute(
        """
        UPDATE documents
        SET
            edit_accessed_at = ?,
            expires_at = ?
        WHERE id = ?
        """,
        (
            to_db_time(now_utc()),
            new_expiration(),
            document_id,
        ),
    )


def renew_pdf_document_by_id(document_id: int) -> None:
    execute(
        """
        UPDATE pdf_documents
        SET
            edit_accessed_at = ?,
            expires_at = ?
        WHERE id = ?
        """,
        (
            to_db_time(now_utc()),
            new_expiration(),
            document_id,
        ),
    )


def require_pdf_upload_link(upload_code: str) -> None:
    if not current_app.config["PDF_UPLOADS_ENABLED"]:
        abort(404)

    expected_hash = current_app.config["PDF_UPLOAD_CODE_HASH"]
    expected_code = current_app.config["PDF_UPLOAD_CODE"]

    if expected_hash:
        actual_hash = hash_edit_token(upload_code)

        if not secrets.compare_digest(actual_hash, expected_hash):
            abort(404)

        return

    if not expected_code:
        abort(404)

    if not secrets.compare_digest(upload_code, expected_code):
        abort(404)


def get_pdf_storage_dir() -> Path:
    storage_dir = Path(current_app.config["PDF_UPLOAD_DIR"])
    storage_dir.mkdir(parents=True, exist_ok=True)
    return storage_dir


def get_pdf_processing_dir() -> Path:
    processing_dir = Path(current_app.config["PDF_PROCESSING_DIR"])
    processing_dir.mkdir(parents=True, exist_ok=True)
    return processing_dir


def get_pdf_storage_path(stored_filename: str) -> Path:
    if not STORED_PDF_RE.fullmatch(stored_filename):
        abort(404)

    storage_dir = get_pdf_storage_dir().resolve()
    path = (storage_dir / stored_filename).resolve()

    if path.parent != storage_dir:
        abort(404)

    return path


def title_from_filename(filename: str) -> str:
    title = Path(filename).stem
    title = title.replace("-", " ").replace("_", " ").strip()
    return title[:MAX_TITLE_CHARS]


def normalize_original_filename(filename: str) -> str:
    original_filename = Path(filename).name.strip()

    if not original_filename:
        original_filename = "document.pdf"

    if len(original_filename) > 240:
        stem = Path(original_filename).stem[:220]
        original_filename = f"{ stem }.pdf"

    return original_filename


def get_pdf_upload() -> object:
    upload = request.files.get("pdf")

    if upload is None or not upload.filename:
        abort_json(400, "PDF file is required")

    original_filename = normalize_original_filename(upload.filename)

    if Path(original_filename).suffix.lower() != ".pdf":
        abort_json(400, "Only .pdf files are supported")

    content_type = (upload.content_type or "").lower()

    if content_type not in ALLOWED_PDF_CONTENT_TYPES:
        abort_json(
            400,
            "Uploaded file must be a PDF",
            {"content_type": content_type},
        )

    return upload


def reject_pdf(
    message: str,
    status_code: int = 400,
    extra: dict | None = None,
) -> None:
    raise PdfUploadRejected(message, status_code, extra)


def create_temp_pdf_path(prefix: str) -> Path:
    processing_dir = get_pdf_processing_dir()

    fd, path_string = tempfile.mkstemp(
        prefix=prefix,
        suffix=".pdf",
        dir=processing_dir,
    )
    os.close(fd)
    os.chmod(path_string, 0o600)
    return Path(path_string)


def write_upload_to_temp(upload) -> tuple[Path, str, int]:
    original_filename = normalize_original_filename(upload.filename)
    temp_path = create_temp_pdf_path("upload-")
    max_pdf_bytes = current_app.config["MAX_PDF_BYTES"]

    first_bytes = upload.stream.read(5)

    if first_bytes != b"%PDF-":
        temp_path.unlink(missing_ok=True)
        reject_pdf("Uploaded file does not look like a PDF")

    size = len(first_bytes)

    try:
        with temp_path.open("wb") as output:
            output.write(first_bytes)

            while True:
                chunk = upload.stream.read(1024 * 1024)

                if not chunk:
                    break

                size += len(chunk)

                if size > max_pdf_bytes:
                    reject_pdf(
                        "PDF is too large",
                        413,
                        {
                            "pdf_bytes": size,
                            "max_pdf_bytes": max_pdf_bytes,
                        },
                    )

                output.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    return temp_path, original_filename, size


def run_optional_av_scan(path: Path) -> bool:
    command = current_app.config["PDF_AV_SCAN_COMMAND"]

    if not command:
        if current_app.config["PDF_REQUIRE_AV_SCAN"]:
            reject_pdf("PDF malware scanner is not configured", 503)

        return False

    args = shlex.split(command) + [str(path)]

    completed = subprocess.run(
        args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=current_app.config["PDF_PROCESS_TIMEOUT_SECONDS"],
        check=False,
    )

    if completed.returncode != 0:
        reject_pdf(
            "PDF failed malware scan",
            400,
            {
                "scanner_exit_code": completed.returncode,
                "scanner_error": completed.stderr[-1000:],
            },
        )

    return True


def sanitize_pdf(source_path: Path, output_path: Path) -> None:
    if current_app.config["PDF_ALLOW_UNSANITIZED"]:
        shutil.copyfile(source_path, output_path)
        os.chmod(output_path, 0o600)
        return

    sanitizer_path = current_app.config["PDF_SANITIZER_PATH"]

    if not sanitizer_path:
        reject_pdf("PDF sanitizer is not configured", 503)

    command = [
        sanitizer_path,
        "-dSAFER",
        "-dBATCH",
        "-dNOPAUSE",
        "-dQUIET",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        "-dShowAnnots=false",
        "-dShowAcroForm=false",
        "-dPrinted=false",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        f"-sOutputFile={ output_path }",
        str(source_path),
    ]

    completed = subprocess.run(
        command,
        cwd=get_pdf_processing_dir(),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=current_app.config["PDF_PROCESS_TIMEOUT_SECONDS"],
        check=False,
    )

    if completed.returncode != 0:
        reject_pdf(
            "PDF could not be sanitized",
            400,
            {
                "sanitizer_exit_code": completed.returncode,
                "sanitizer_error": completed.stderr[-1000:],
            },
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        reject_pdf("PDF sanitizer produced no output")

    os.chmod(output_path, 0o600)


def get_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)

            if not chunk:
                break

            digest.update(chunk)

    return digest.hexdigest()


def verify_no_forbidden_pdf_features(path: Path) -> None:
    content = path.read_bytes()

    if not content.startswith(b"%PDF-"):
        reject_pdf("Sanitized output does not look like a PDF")

    for token, description in FORBIDDEN_PDF_FEATURES.items():
        if token in content:
            reject_pdf(
                "Sanitized PDF still contains unsupported features",
                400,
                {
                    "feature": description,
                    "token": token.decode("ascii", errors="replace"),
                },
            )


def inspect_pdf_text_and_pages(path: Path) -> tuple[int, int, int, float]:
    try:
        from pypdf import PdfReader
    except ImportError:
        if current_app.config["PDF_REQUIRE_SELECTABLE_TEXT"]:
            reject_pdf("PDF text inspection is not available", 503)

        return 0, 0, 0, 0.0

    try:
        reader = PdfReader(str(path), strict=False)

        if reader.is_encrypted:
            reject_pdf("Encrypted PDFs are not supported")

        page_count = len(reader.pages)

        if page_count == 0:
            reject_pdf("PDF has no pages")

        if page_count > current_app.config["MAX_PDF_PAGES"]:
            reject_pdf(
                "PDF has too many pages",
                413,
                {
                    "page_count": page_count,
                    "max_pdf_pages": current_app.config["MAX_PDF_PAGES"],
                },
            )

        text_char_count = 0
        text_page_count = 0
        text_page_min_chars = current_app.config[
            "PDF_TEXT_PAGE_MIN_CHARS"
        ]

        for page in reader.pages:
            page_text = page.extract_text() or ""
            page_text_chars = len("".join(page_text.split()))

            text_char_count += page_text_chars

            if page_text_chars >= text_page_min_chars:
                text_page_count += 1
    except PdfUploadRejected:
        raise
    except Exception as error:
        reject_pdf(
            "PDF could not be inspected after sanitization",
            400,
            {"inspection_error": str(error)[:500]},
        )

    text_page_percent = (text_page_count / page_count) * 100

    if current_app.config["PDF_REQUIRE_SELECTABLE_TEXT"]:
        required_percent = current_app.config[
            "MIN_PDF_TEXT_PAGE_PERCENT"
        ]

        if text_page_percent < required_percent:
            reject_pdf(
                "PDF does not appear to contain selectable text on enough pages",
                400,
                {
                    "text_char_count": text_char_count,
                    "text_page_count": text_page_count,
                    "text_page_percent": round(text_page_percent, 2),
                    "required_text_page_percent": required_percent,
                    "text_page_min_chars": text_page_min_chars,
                    "page_count": page_count,
                },
            )

    return (
        page_count,
        text_char_count,
        text_page_count,
        text_page_percent,
    )

def process_pdf_upload(upload) -> PdfProcessingResult:
    source_path: Path | None = None
    sanitized_temp_path: Path | None = None
    final_path: Path | None = None

    try:
        source_path, original_filename, _upload_size = (
            write_upload_to_temp(upload)
        )
        av_scanned = run_optional_av_scan(source_path)

        sanitized_temp_path = create_temp_pdf_path("sanitized-")
        sanitize_pdf(source_path, sanitized_temp_path)
        verify_no_forbidden_pdf_features(sanitized_temp_path)

        (
            page_count,
            text_char_count,
            text_page_count,
            text_page_percent,
        ) = inspect_pdf_text_and_pages(sanitized_temp_path)

        stored_filename = f"{ random_slug(32) }.pdf"
        final_path = get_pdf_storage_path(stored_filename)
        os.replace(sanitized_temp_path, final_path)
        sanitized_temp_path = None

        file_size_bytes = final_path.stat().st_size
        sanitized_at = to_db_time(now_utc())
        pdf_sha256 = get_file_sha256(final_path)

        return PdfProcessingResult(
            stored_filename=stored_filename,
            original_filename=original_filename,
            file_size_bytes=file_size_bytes,
            sanitized_at=sanitized_at,
            pdf_sha256=pdf_sha256,
            page_count=page_count,
            text_char_count=text_char_count,
            text_page_count=text_page_count,
            text_page_percent=text_page_percent,
            safety_status=(
                "dev-unsanitized"
                if current_app.config["PDF_ALLOW_UNSANITIZED"]
                else (
                    "sanitized-av-scanned"
                    if av_scanned
                    else "sanitized"
                )
            ),
        )
    finally:
        if source_path is not None:
            source_path.unlink(missing_ok=True)

        if sanitized_temp_path is not None:
            sanitized_temp_path.unlink(missing_ok=True)


def safe_pdf_download_name(row) -> str:
    candidates = [
        f"{ row['title'] }.pdf" if row["title"] else "",
        row["original_filename"],
        "quillqr-document.pdf",
    ]

    for candidate in candidates:
        filename = secure_filename(candidate)

        if filename:
            if not filename.lower().endswith(".pdf"):
                filename = f"{ filename }.pdf"

            return filename

    return "quillqr-document.pdf"


def query_pdf_by_read_slug(read_slug: str):
    return query_one(
        """
        SELECT *
        FROM pdf_documents
        WHERE read_slug = ?
          AND deleted_at IS NULL
        """,
        (read_slug,),
    )


def query_pdf_by_edit_token(edit_token: str):
    return query_one(
        """
        SELECT *
        FROM pdf_documents
        WHERE edit_token_hash = ?
          AND deleted_at IS NULL
        """,
        (hash_edit_token(edit_token),),
    )


def add_common_security_headers(response):
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


def register_routes(app: Flask) -> None:
    @app.after_request
    def after_request(response):
        return add_common_security_headers(response)

    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        ensure_pdf_schema()
        print("Initialized QuillQR database.")

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify(
            {
                "ok": False,
                "error": "request body is too large",
            }
        ), 413

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            app_name=APP_NAME,
            max_content_bytes=MAX_CONTENT_BYTES,
        )

    @app.post("/api/documents")
    def create_document():
        body = get_json_body()

        title = str(body.get("title", ""))
        content = str(body.get("content", ""))
        content_format = str(
            body.get("content_format", "text")
        )

        title, content, content_format = validate_content(
            title,
            content,
            content_format,
        )

        read_slug = create_unique_slug()
        edit_token = create_edit_token()
        edit_token_hash = hash_edit_token(edit_token)

        created_at = to_db_time(now_utc())
        expires_at = new_expiration()

        execute(
            """
            INSERT INTO documents (
                read_slug,
                edit_token_hash,
                title,
                content,
                content_format,
                created_at,
                updated_at,
                edit_accessed_at,
                expires_at,
                deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                read_slug,
                edit_token_hash,
                title,
                content,
                content_format,
                created_at,
                created_at,
                expires_at,
            ),
        )

        return jsonify(
            {
                "ok": True,
                "read_slug": read_slug,
                "public_url": public_document_url(read_slug),
                "edit_url": edit_document_url(edit_token),
                "expires_at": expires_at,
            }
        )

    @app.get("/api/documents/<read_slug>")
    def get_document_json(read_slug: str):
        row = query_one(
            """
            SELECT *
            FROM documents
            WHERE read_slug = ?
              AND deleted_at IS NULL
            """,
            (read_slug,),
        )

        if row is None or is_expired(row):
            abort_json(404, "document not found")

        return jsonify(
            {
                "ok": True,
                "read_slug": row["read_slug"],
                "title": row["title"],
                "content": row["content"],
                "content_format": row["content_format"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "expires_at": row["expires_at"],
            }
        )

    @app.get("/d/<read_slug>")
    def view_document(read_slug: str):
        row = query_one(
            """
            SELECT *
            FROM documents
            WHERE read_slug = ?
              AND deleted_at IS NULL
            """,
            (read_slug,),
        )

        if row is None or is_expired(row):
            abort(404)

        return render_template(
            "document.html",
            app_name=APP_NAME,
            document=row,
            public_url=public_document_url(row["read_slug"]),
        )

    @app.get("/e/<edit_token>")
    def edit_document(edit_token: str):
        token_hash = hash_edit_token(edit_token)

        row = query_one(
            """
            SELECT *
            FROM documents
            WHERE edit_token_hash = ?
              AND deleted_at IS NULL
            """,
            (token_hash,),
        )

        if row is None or is_expired(row):
            abort(404)

        renew_document_by_id(row["id"])

        refreshed = query_one(
            """
            SELECT *
            FROM documents
            WHERE id = ?
            """,
            (row["id"],),
        )

        return render_template(
            "edit.html",
            app_name=APP_NAME,
            document=refreshed,
            edit_token=edit_token,
            public_url=public_document_url(row["read_slug"]),
            max_content_bytes=MAX_CONTENT_BYTES,
        )

    @app.put("/api/edit/<edit_token>")
    def update_document(edit_token: str):
        token_hash = hash_edit_token(edit_token)

        row = query_one(
            """
            SELECT *
            FROM documents
            WHERE edit_token_hash = ?
              AND deleted_at IS NULL
            """,
            (token_hash,),
        )

        if row is None or is_expired(row):
            abort_json(404, "document not found")

        body = get_json_body()

        title = str(body.get("title", ""))
        content = str(body.get("content", ""))
        content_format = str(
            body.get("content_format", "text")
        )

        title, content, content_format = validate_content(
            title,
            content,
            content_format,
        )

        updated_at = to_db_time(now_utc())
        expires_at = new_expiration()

        execute(
            """
            UPDATE documents
            SET
                title = ?,
                content = ?,
                content_format = ?,
                updated_at = ?,
                edit_accessed_at = ?,
                expires_at = ?
            WHERE id = ?
            """,
            (
                title,
                content,
                content_format,
                updated_at,
                updated_at,
                expires_at,
                row["id"],
            ),
        )

        return jsonify(
            {
                "ok": True,
                "public_url": public_document_url(
                    row["read_slug"]
                ),
                "expires_at": expires_at,
            }
        )

    @app.get("/p/<upload_code>")
    def new_pdf_document(upload_code: str):
        require_pdf_upload_link(upload_code)

        return render_template(
            "pdf/index.html",
            app_name=APP_NAME,
            max_pdf_bytes=current_app.config["MAX_PDF_BYTES"],
            require_selectable_text=current_app.config[
                "PDF_REQUIRE_SELECTABLE_TEXT"
            ],
            min_text_page_percent=current_app.config[
                "MIN_PDF_TEXT_PAGE_PERCENT"
            ],
            text_page_min_chars=current_app.config[
                "PDF_TEXT_PAGE_MIN_CHARS"
            ],
            allow_unsanitized=current_app.config["PDF_ALLOW_UNSANITIZED"],
        )

    @app.post("/p/<upload_code>")
    def create_pdf_document(upload_code: str):
        require_pdf_upload_link(upload_code)

        upload = get_pdf_upload()

        try:
            processed = process_pdf_upload(upload)
        except PdfUploadRejected as error:
            abort_json(error.status_code, error.message, error.extra)

        read_slug = create_unique_pdf_slug()
        edit_token = create_edit_token()
        edit_token_hash = hash_edit_token(edit_token)
        title = title_from_filename(processed.original_filename)

        created_at = to_db_time(now_utc())
        expires_at = new_expiration()

        execute(
            """
            INSERT INTO pdf_documents (
                read_slug,
                edit_token_hash,
                title,
                stored_filename,
                original_filename,
                file_size_bytes,
                sanitized_at,
                pdf_sha256,
                page_count,
                text_char_count,
                text_page_count,
                text_page_percent,
                safety_status,
                created_at,
                updated_at,
                edit_accessed_at,
                expires_at,
                deleted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
            """,
            (
                read_slug,
                edit_token_hash,
                title,
                processed.stored_filename,
                processed.original_filename,
                processed.file_size_bytes,
                processed.sanitized_at,
                processed.pdf_sha256,
                processed.page_count,
                processed.text_char_count,
                processed.text_page_count,
                processed.text_page_percent,
                processed.safety_status,
                created_at,
                created_at,
                expires_at,
            ),
        )

        return jsonify(
            {
                "ok": True,
                "read_slug": read_slug,
                "public_url": public_pdf_document_url(read_slug),
                "edit_url": edit_pdf_document_url(edit_token),
                "expires_at": expires_at,
                "file_size_bytes": processed.file_size_bytes,
                "page_count": processed.page_count,
                "text_char_count": processed.text_char_count,
                "text_page_count": processed.text_page_count,
                "text_page_percent": processed.text_page_percent,
                "safety_status": processed.safety_status,
            }
        )

    @app.get("/p/d/<read_slug>")
    def view_pdf_document(read_slug: str):
        row = query_pdf_by_read_slug(read_slug)

        if row is None or is_expired(row):
            abort(404)

        return render_template(
            "pdf/document.html",
            app_name=APP_NAME,
            document=row,
            public_url=public_pdf_document_url(row["read_slug"]),
            file_url=versioned_pdf_file_url(row),
        )

    @app.get("/p/e/<edit_token>")
    def edit_pdf_document(edit_token: str):
        row = query_pdf_by_edit_token(edit_token)

        if row is None or is_expired(row):
            abort(404)

        renew_pdf_document_by_id(row["id"])

        refreshed = query_one(
            """
            SELECT *
            FROM pdf_documents
            WHERE id = ?
            """,
            (row["id"],),
        )

        return render_template(
            "pdf/edit.html",
            app_name=APP_NAME,
            document=refreshed,
            edit_token=edit_token,
            public_url=public_pdf_document_url(row["read_slug"]),
            max_pdf_bytes=current_app.config["MAX_PDF_BYTES"],
            require_selectable_text=current_app.config[
                "PDF_REQUIRE_SELECTABLE_TEXT"
            ],
            min_text_page_percent=current_app.config[
                "MIN_PDF_TEXT_PAGE_PERCENT"
            ],
            text_page_min_chars=current_app.config[
                "PDF_TEXT_PAGE_MIN_CHARS"
            ],
            allow_unsanitized=current_app.config["PDF_ALLOW_UNSANITIZED"],
        )

    @app.post("/p/e/<edit_token>")
    def update_pdf_document(edit_token: str):
        row = query_pdf_by_edit_token(edit_token)

        if row is None or is_expired(row):
            abort_json(404, "PDF document not found")

        upload = get_pdf_upload()

        try:
            processed = process_pdf_upload(upload)
        except PdfUploadRejected as error:
            abort_json(error.status_code, error.message, error.extra)

        old_storage_path = get_pdf_storage_path(row["stored_filename"])
        updated_at = to_db_time(now_utc())
        expires_at = new_expiration()

        execute(
            """
            UPDATE pdf_documents
            SET
                title = ?,
                stored_filename = ?,
                original_filename = ?,
                file_size_bytes = ?,
                sanitized_at = ?,
                pdf_sha256 = ?,
                page_count = ?,
                text_char_count = ?,
                text_page_count = ?,
                text_page_percent = ?,
                safety_status = ?,
                updated_at = ?,
                edit_accessed_at = ?,
                expires_at = ?
            WHERE id = ?
            """,
            (
                title_from_filename(processed.original_filename),
                processed.stored_filename,
                processed.original_filename,
                processed.file_size_bytes,
                processed.sanitized_at,
                processed.pdf_sha256,
                processed.page_count,
                processed.text_char_count,
                processed.text_page_count,
                processed.text_page_percent,
                processed.safety_status,
                updated_at,
                updated_at,
                expires_at,
                row["id"],
            ),
        )

        old_storage_path.unlink(missing_ok=True)

        return jsonify(
            {
                "ok": True,
                "public_url": public_pdf_document_url(
                    row["read_slug"]
                ),
                "expires_at": expires_at,
                "file_size_bytes": processed.file_size_bytes,
                "page_count": processed.page_count,
                "text_char_count": processed.text_char_count,
                "text_page_count": processed.text_page_count,
                "text_page_percent": processed.text_page_percent,
                "safety_status": processed.safety_status,
            }
        )

    @app.get("/p/file/<read_slug>")
    def serve_pdf_file(read_slug: str):
        row = query_pdf_by_read_slug(read_slug)

        if row is None or is_expired(row):
            abort(404)

        path = get_pdf_storage_path(row["stored_filename"])

        if not path.exists():
            abort(404)

        response = send_file(
            path,
            mimetype="application/pdf",
            as_attachment=False,
            download_name=safe_pdf_download_name(row),
            conditional=True,
        )
        response.headers["Content-Disposition"] = (
            f"inline; filename={ safe_pdf_download_name(row) }"
        )
        response.headers["Content-Security-Policy"] = "sandbox"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
