from __future__ import annotations

import hashlib
import os
import secrets
import string
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from db import close_db, execute, init_db, query_one


APP_NAME = "QuillQR"
DEFAULT_EXPIRATION_DAYS = 90

MAX_CONTENT_BYTES = 50 * 1024
MAX_TITLE_CHARS = 120

ALLOWED_FORMATS = {"text", "markdown"}

SLUG_ALPHABET = (
    string.ascii_lowercase
    + string.ascii_uppercase
    + string.digits
)


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)

    instance_path = Path(app.instance_path)
    instance_path.mkdir(parents=True, exist_ok=True)

    app.config.from_mapping(
        DATABASE=str(instance_path / "quillqr.sqlite3"),

        # This limits the full request body.
        # Nginx should also enforce client_max_body_size.
        MAX_CONTENT_LENGTH=128 * 1024,
    )

    app.teardown_appcontext(close_db)

    register_routes(app)

    return app


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


def public_document_url(read_slug: str) -> str:
    return url_for(
        "view_document",
        read_slug=read_slug,
        _external=True,
    )


def edit_document_url(edit_token: str) -> str:
    return url_for(
        "edit_document",
        edit_token=edit_token,
        _external=True,
    )


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


def register_routes(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        print("Initialized QuillQR database.")

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


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)