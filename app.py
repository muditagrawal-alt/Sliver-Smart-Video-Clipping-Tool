from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import mimetypes
import os
import secrets
import sqlite3
import threading
import traceback
from datetime import datetime, timezone
from email import message_from_bytes
from email.policy import HTTP
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote
from wsgiref.simple_server import make_server
from wsgiref.util import FileWrapper

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
ASSETS_DIR = ROOT_DIR / "assets"
TEMPLATES_DIR = ROOT_DIR / "templates"
DATA_DIR = ROOT_DIR / "web_data"
UPLOADS_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
DB_PATH = DATA_DIR / "sliver.sqlite3"

# FIX: ensure_storage() was called on every request (including every static
# file fetch).  Run it once at startup via this flag instead.
_storage_initialised = False

SESSION_COOKIE = "sliver_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 200_000
DEFAULT_SECRET = "sliver-dev-secret"
SECRET_KEY = os.environ.get("SLIVER_SECRET_KEY", DEFAULT_SECRET).encode("utf-8")

env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "xml"]),
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_duration(seconds: int) -> str:
    seconds = max(int(seconds), 0)
    if seconds < 60:
        return f"{seconds} sec"
    minutes, remainder = divmod(seconds, 60)
    if remainder == 0:
        return f"{minutes} min"
    return f"{minutes} min {remainder} sec"


def format_timestamp(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    return dt.astimezone().strftime("%b %d, %Y")


def template_response(start_response, template_name: str, context: dict, status: str = "200 OK"):
    html = env.get_template(template_name).render(**context)
    return respond(start_response, status, html)


def respond(start_response, status: str, body: str | bytes, headers: list[tuple[str, str]] | None = None):
    final_headers = [("Content-Type", "text/html; charset=utf-8")]
    if headers:
        final_headers.extend(headers)

    if isinstance(body, str):
        body = body.encode("utf-8")

    final_headers.append(("Content-Length", str(len(body))))
    start_response(status, final_headers)
    return [body]


def json_response(start_response, payload: dict, status: str = "200 OK", headers: list[tuple[str, str]] | None = None):
    body = json.dumps(payload).encode("utf-8")
    final_headers = [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))]
    if headers:
        final_headers.extend(headers)
    start_response(status, final_headers)
    return [body]


def redirect(start_response, location: str, headers: list[tuple[str, str]] | None = None):
    final_headers = [("Location", location)]
    if headers:
        final_headers.extend(headers)
    start_response("303 See Other", final_headers)
    return [b""]


def bad_request(start_response, message: str):
    return json_response(start_response, {"ok": False, "error": message}, status="400 Bad Request")


def unauthorized(start_response):
    return json_response(start_response, {"ok": False, "error": "Please sign in first."}, status="401 Unauthorized")


def not_found(start_response, message: str = "Not found"):
    return respond(start_response, "404 Not Found", message)


def parse_query_string(environ) -> dict[str, str]:
    query = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    return {key: values[0] for key, values in query.items()}


def parse_urlencoded_form(environ) -> dict[str, str]:
    length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(length) if length else b""
    parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    return {key: values[0] for key, values in parsed.items()}


def parse_multipart_form(environ) -> dict:
    """
    Parse a multipart/form-data request body without using the deprecated
    `cgi` module (removed in Python 3.13).

    Returns a dict mapping field names to FieldItem objects with attributes:
        .filename  — original filename string (or "")
        .value     — bytes content (for files) or str (for text fields)
        .file      — BytesIO for streaming reads

    Also supports getfirst(name, default) for text fields.
    """
    content_type = environ.get("CONTENT_TYPE", "")
    content_length = int(environ.get("CONTENT_LENGTH") or 0)
    body = environ["wsgi.input"].read(content_length) if content_length else b""

    # Build a fake email message so email.parser can parse multipart boundaries
    raw = f"Content-Type: {content_type}\r\n\r\n".encode() + body
    msg = message_from_bytes(raw, policy=HTTP)

    result = _MultipartForm()

    if msg.is_multipart():
        for part in msg.iter_parts():
            disposition = part.get("Content-Disposition", "")
            params = _parse_disposition(disposition)
            name     = params.get("name", "")
            filename = params.get("filename", "")
            payload  = part.get_payload(decode=True) or b""

            item = _FieldItem(
                name=name,
                filename=filename,
                value=payload,
            )
            result._fields[name] = item

    return result


def _parse_disposition(header: str) -> dict[str, str]:
    """Extract key=value pairs from a Content-Disposition header."""
    params: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if "=" in part:
            key, _, val = part.partition("=")
            params[key.strip().lower()] = val.strip().strip('"')
    return params


class _FieldItem:
    """Minimal replacement for a cgi.FieldStorage part."""

    def __init__(self, name: str, filename: str, value: bytes) -> None:
        self.name     = name
        self.filename = filename
        self.value    = value
        self.file     = io.BytesIO(value)


class _MultipartForm:
    """Dict-like container returned by parse_multipart_form."""

    def __init__(self) -> None:
        self._fields: dict[str, _FieldItem] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._fields

    def __getitem__(self, key: str) -> _FieldItem:
        return self._fields[key]

    def getfirst(self, key: str, default: str = "") -> str:
        item = self._fields.get(key)
        if item is None:
            return default
        return item.value.decode("utf-8", errors="replace") if isinstance(item.value, bytes) else item.value


def parse_cookies(environ) -> dict[str, str]:
    cookie_header = environ.get("HTTP_COOKIE", "")
    cookies = {}
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.strip().split("=", 1)
        cookies[key] = unquote(value)
    if SESSION_COOKIE not in cookies:
        qs = parse_qs(environ.get("QUERY_STRING", ""))
        if SESSION_COOKIE in qs:
            cookies[SESSION_COOKIE] = qs[SESSION_COOKIE][0]
    return cookies


def sign_session(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).decode("ascii")
    signature = hmac.new(SECRET_KEY, encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def unsign_session(token: str) -> dict | None:
    try:
        encoded, signature = token.rsplit(".", 1)
    except ValueError:
        return None

    expected = hmac.new(SECRET_KEY, encoded.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None

    try:
        payload = json.loads(base64.urlsafe_b64decode(encoded.encode("ascii")))
    except (ValueError, json.JSONDecodeError):
        return None

    return payload


def session_cookie(user_id: int) -> tuple[str, str]:
    token = sign_session({"user_id": int(user_id), "issued_at": now_utc().timestamp()})
    cookie = (
        f"{SESSION_COOKIE}={quote(token)}; Path=/; Max-Age={SESSION_MAX_AGE}; "
        "HttpOnly; SameSite=Lax"
    )
    return "Set-Cookie", cookie


def clear_session_cookie() -> tuple[str, str]:
    return "Set-Cookie", f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored_value: str) -> bool:
    try:
        salt_hex, digest_hex = stored_value.split(":", 1)
    except ValueError:
        return False

    computed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt_hex),
        PASSWORD_ITERATIONS,
    ).hex()
    return hmac.compare_digest(computed, digest_hex)


def safe_filename(filename: str) -> str:
    name = Path(filename or "video.mp4").name
    cleaned = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in name)
    return cleaned or "video.mp4"


def ensure_storage() -> None:
    """
    Create directories and database tables on first call only.

    FIX: was called on every single HTTP request (including /static/* assets).
    Now guarded by _storage_initialised so it runs exactly once per process.
    FIX: added covering indexes on clips(user_id) and jobs(user_id) — the two
         most common query predicates — so profile and job-status lookups don't
         do full table scans as the dataset grows.
    """
    global _storage_initialised
    if _storage_initialised:
        return
    _storage_initialised = True

    for folder in (DATA_DIR, UPLOADS_DIR, GENERATED_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
        connection.execute("PRAGMA journal_mode=WAL;")
        connection.execute("PRAGMA foreign_keys=ON;")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS clips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                duration_sec INTEGER NOT NULL,
                output_relative_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                source_name TEXT NOT NULL,
                duration_sec INTEGER NOT NULL,
                status TEXT NOT NULL,
                progress INTEGER NOT NULL,
                message TEXT NOT NULL,
                clip_payload TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        # FIX: indexes on the two most-queried columns
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_clips_user_id ON clips(user_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_jobs_user_id ON jobs(user_id)"
        )
        connection.commit()


def db_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def get_user_by_id(user_id: int):
    with db_connection() as connection:
        return connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def get_user_by_email(email: str):
    with db_connection() as connection:
        return connection.execute("SELECT * FROM users WHERE lower(email) = lower(?)", (email,)).fetchone()


def create_user(name: str, email: str, password: str):
    created_at = now_utc().isoformat()
    try:
        with db_connection() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (name, email, password_hash, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, hash_password(password), created_at),
            )
            connection.commit()
            return get_user_by_id(cursor.lastrowid)
    except sqlite3.IntegrityError:
        return None


def build_clip_payload(
    clip_id: int,
    source_name: str,
    duration_sec: int,
    output_relative_path: str,
    created_at: str,
) -> dict[str, Any]:
    return {
        "id": clip_id,
        "source_name": source_name,
        "duration_sec": duration_sec,
        "duration_label": format_duration(duration_sec),
        "created_at": created_at,
        "created_label": format_timestamp(created_at),
        "video_url": f"/media/{quote(output_relative_path)}",
        "download_url": f"/clips/{clip_id}/download",
    }


def insert_clip(user_id: int, source_name: str, duration_sec: int, output_relative_path: str, created_at: str) -> int:
    with db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO clips (user_id, source_name, duration_sec, output_relative_path, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, source_name, duration_sec, output_relative_path, created_at),
        )
        connection.commit()
        return int(cursor.lastrowid)


def list_clips_for_user(user_id: int) -> list[dict[str, Any]]:
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, source_name, duration_sec, output_relative_path, created_at
            FROM clips
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()

    return [
        build_clip_payload(
            clip_id=row["id"],
            source_name=row["source_name"],
            duration_sec=row["duration_sec"],
            output_relative_path=row["output_relative_path"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def get_clip_for_user(user_id: int, clip_id: int):
    with db_connection() as connection:
        return connection.execute(
            """
            SELECT id, source_name, duration_sec, output_relative_path, created_at
            FROM clips
            WHERE id = ? AND user_id = ?
            """,
            (clip_id, user_id),
        ).fetchone()


def build_clip_stats(clips: list[dict[str, Any]]) -> dict[str, str | int]:
    total_seconds = sum(int(clip["duration_sec"]) for clip in clips)
    return {
        "total_clips": len(clips),
        "total_runtime": format_duration(total_seconds),
        "latest_clip": clips[0]["created_label"] if clips else "No exports yet",
    }


def create_job(user_id: int, source_name: str, duration_sec: int) -> str:
    job_id = secrets.token_hex(12)
    now = now_utc().isoformat()
    with db_connection() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, user_id, source_name, duration_sec, status, progress, message, clip_payload, error, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, user_id, source_name, duration_sec, "queued", 0, "Upload received. Preparing your summary.", None, None, now, now)
        )
        connection.commit()
    return job_id


def update_job(job_id: str, **changes) -> None:
    """
    Update one or more columns on a job row atomically.

    FIX: the original implementation did a SELECT then a separate UPDATE —
    two round-trips that are not atomic and waste a query.  We now build the
    UPDATE directly and skip the unnecessary preflight SELECT.
    """
    if not changes:
        return

    update_fields: list[str] = []
    update_values: list = []

    for key, value in changes.items():
        if key == "clip":
            update_fields.append("clip_payload = ?")
            update_values.append(json.dumps(value) if value is not None else None)
        else:
            update_fields.append(f"{key} = ?")
            update_values.append(value)

    update_fields.append("updated_at = ?")
    update_values.append(now_utc().isoformat())
    update_values.append(job_id)

    query = f"UPDATE jobs SET {', '.join(update_fields)} WHERE id = ?"
    with db_connection() as connection:
        connection.execute(query, tuple(update_values))
        connection.commit()


def get_job(job_id: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            return None
        
        job_dict = dict(row)
        if job_dict.get("clip_payload"):
            try:
                job_dict["clip"] = json.loads(job_dict["clip_payload"])
            except json.JSONDecodeError:
                job_dict["clip"] = None
        else:
            job_dict["clip"] = None
            
        return job_dict


def public_job_payload(job: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": job["id"],
        "source_name": job["source_name"],
        "duration_sec": job["duration_sec"],
        "duration_label": format_duration(job["duration_sec"]),
        "status": job["status"],
        "progress": int(job["progress"]),
        "message": job["message"],
        "clip": job["clip"],
        "error": job["error"],
    }


def current_user(environ):
    token = parse_cookies(environ).get(SESSION_COOKIE)
    if not token:
        return None

    payload = unsign_session(token)
    if not payload or "user_id" not in payload:
        return None

    return get_user_by_id(int(payload["user_id"]))


def media_path(relative_path: str) -> Path | None:
    # Security: media files must be confined to uploads/ or generated/ subdirectories
    parts = Path(relative_path).parts
    if not parts or parts[0] not in {"generated", "uploads"}:
        return None
    resolved = (DATA_DIR / relative_path).resolve()
    if not (GENERATED_DIR.resolve() in resolved.parents or UPLOADS_DIR.resolve() in resolved.parents or resolved in (GENERATED_DIR.resolve(), UPLOADS_DIR.resolve())):
        return None
    return resolved


def static_path(relative_path: str) -> Path | None:
    resolved = (STATIC_DIR / relative_path).resolve()
    if STATIC_DIR.resolve() not in resolved.parents and resolved != STATIC_DIR.resolve():
        return None
    return resolved


def assets_path(relative_path: str) -> Path | None:
    resolved = (ASSETS_DIR / relative_path).resolve()
    if ASSETS_DIR.resolve() not in resolved.parents and resolved != ASSETS_DIR.resolve():
        return None
    return resolved


def file_response(environ, start_response, file_path: Path, download_name: str | None = None):
    if not file_path.exists() or not file_path.is_file():
        return not_found(start_response)

    file_size = file_path.stat().st_size
    mime_type, _ = mimetypes.guess_type(file_path.as_posix())
    mime_type = mime_type or "application/octet-stream"

    http_range = environ.get("HTTP_RANGE", "").strip() if environ else ""

    # Support HTTP 206 Partial Content (Range requests) for HTML5 video seeking
    if http_range.startswith("bytes="):
        range_spec = http_range.removeprefix("bytes=").split(",")[0].strip()
        parts = range_spec.split("-")
        try:
            if parts[0] and parts[1]:
                start = int(parts[0])
                end = int(parts[1])
            elif parts[0]:
                start = int(parts[0])
                end = file_size - 1
            elif parts[1]:
                length = int(parts[1])
                start = max(0, file_size - length)
                end = file_size - 1
            else:
                start = 0
                end = file_size - 1
        except ValueError:
            start = 0
            end = file_size - 1

        if start >= file_size or end >= file_size or start > end:
            headers = [
                ("Content-Range", f"bytes */{file_size}"),
                ("Content-Type", mime_type),
            ]
            start_response("416 Range Not Satisfiable", headers)
            return [b""]

        length = end - start + 1
        headers = [
            ("Content-Type", mime_type),
            ("Content-Range", f"bytes {start}-{end}/{file_size}"),
            ("Content-Length", str(length)),
            ("Accept-Ranges", "bytes"),
        ]
        if download_name:
            headers.append(("Content-Disposition", f'attachment; filename="{download_name}"'))

        start_response("206 Partial Content", headers)

        def file_iterator():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                chunk_size = 64 * 1024
                while remaining > 0:
                    read_amount = min(chunk_size, remaining)
                    chunk = f.read(read_amount)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return file_iterator()

    headers = [
        ("Content-Type", mime_type),
        ("Content-Length", str(file_size)),
        ("Accept-Ranges", "bytes"),
    ]
    if download_name:
        headers.append(("Content-Disposition", f'attachment; filename="{download_name}"'))

    start_response("200 OK", headers)
    return FileWrapper(open(file_path, "rb"))


def page_context(environ, user=None, **extra):
    current = user if user is not None else current_user(environ)
    return {
        "user": current,
        "request_path": environ.get("PATH_INFO", "/"),
        "workspace_href": "/workspace" if current else "/auth?mode=signup",
        "site_year": now_utc().year,
        **extra,
    }


def handle_home(environ, start_response):
    return template_response(start_response, "home.html", page_context(environ))


def handle_auth_get(environ, start_response):
    user = current_user(environ)
    if user:
        return redirect(start_response, "/workspace")

    query = parse_query_string(environ)
    mode = "signup" if query.get("mode") == "signup" else "login"
    context = page_context(
        environ,
        auth_mode=mode,
        auth_error=query.get("error"),
        auth_notice=query.get("notice"),
    )
    return template_response(start_response, "auth.html", context)


def handle_signup(environ, start_response):
    form = parse_urlencoded_form(environ)
    name = form.get("name", "").strip()
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")

    if len(name) < 2 or "@" not in email or len(password) < 6:
        return redirect(
            start_response,
            "/auth?mode=signup&error=" + quote("Fill every field and use a 6+ character password."),
        )

    user = create_user(name, email, password)
    if not user:
        return redirect(
            start_response,
            "/auth?mode=signup&error=" + quote("That email is already registered."),
        )

    return redirect(start_response, "/workspace", headers=[session_cookie(int(user["id"]))])


def handle_login(environ, start_response):
    form = parse_urlencoded_form(environ)
    email = form.get("email", "").strip().lower()
    password = form.get("password", "")
    user = get_user_by_email(email)

    if not user or not verify_password(password, user["password_hash"]):
        return redirect(
            start_response,
            "/auth?mode=login&error=" + quote("Incorrect email or password."),
        )

    return redirect(start_response, "/workspace", headers=[session_cookie(int(user["id"]))])


def handle_logout(start_response):
    return redirect(start_response, "/", headers=[clear_session_cookie()])


def handle_workspace(environ, start_response):
    user = current_user(environ)
    if not user:
        return redirect(start_response, "/auth?mode=login")

    clips = list_clips_for_user(int(user["id"]))
    context = page_context(
        environ,
        user=user,
        latest_clip=clips[0] if clips else None,
    )
    return template_response(start_response, "workspace.html", context)


def handle_profile(environ, start_response):
    user = current_user(environ)
    if not user:
        return redirect(start_response, "/auth?mode=login")

    clips = list_clips_for_user(int(user["id"]))
    context = page_context(
        environ,
        user=user,
        clips=clips,
        stats=build_clip_stats(clips),
    )
    return template_response(start_response, "profile.html", context)


def save_uploaded_video(file_item: _FieldItem, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as output_file:
        while True:
            chunk = file_item.file.read(1024 * 1024)
            if not chunk:
                break
            output_file.write(chunk)


def run_clip_job(
    job_id: str,
    user_id: int,
    filename: str,
    duration_sec: int,
    upload_path: Path,
    generated_dir: Path,
    prompt: str = "",
):
    update_job(job_id, status="running", progress=3, message="Loading summarizer models.")

    try:
        from face_clip.pipeline.process_video import process_video

        def progress_callback(percent: int, message: str):
            update_job(job_id, status="running", progress=percent, message=message)

        output_path = Path(
            process_video(
                video_path=upload_path.as_posix(),
                target_clip_duration_sec=duration_sec,
                output_dir=generated_dir.as_posix(),
                progress_callback=progress_callback,
                prompt=prompt,
            )
        ).resolve()
        relative_output = output_path.relative_to(DATA_DIR).as_posix()
        created_at = now_utc().isoformat()

        # Compute actual duration of generated clip
        actual_duration = duration_sec
        try:
            import cv2
            cap_check = cv2.VideoCapture(str(output_path))
            if cap_check.isOpened():
                frame_cnt = cap_check.get(cv2.CAP_PROP_FRAME_COUNT)
                fps_val = cap_check.get(cv2.CAP_PROP_FPS) or 25.0
                if frame_cnt > 0 and fps_val > 0:
                    actual_duration = max(1, round(frame_cnt / fps_val))
                cap_check.release()
        except Exception:
            pass

        clip_id = insert_clip(
            user_id=user_id,
            source_name=filename,
            duration_sec=actual_duration,
            output_relative_path=relative_output,
            created_at=created_at,
        )
        clip_payload = build_clip_payload(
            clip_id=clip_id,
            source_name=filename,
            duration_sec=actual_duration,
            output_relative_path=relative_output,
            created_at=created_at,
        )
        update_job(
            job_id,
            status="completed",
            progress=100,
            message="Summary ready.",
            clip=clip_payload,
            error=None,
        )
    except Exception as exc:
        traceback.print_exc()
        update_job(
            job_id,
            status="failed",
            message="Summary generation failed.",
            error=str(exc),
        )


def handle_process(environ, start_response):
    user = current_user(environ)
    if not user:
        return unauthorized(start_response)

    form = parse_multipart_form(environ)
    if "video" not in form:
        return bad_request(start_response, "Choose a video before generating a summary.")

    video_field = form["video"]
    if not getattr(video_field, "filename", ""):
        return bad_request(start_response, "Choose a video before generating a summary.")

    duration_text = form.getfirst("duration", "30").strip()
    try:
        duration_sec = int(duration_text)
    except ValueError:
        return bad_request(start_response, "Enter the summary length in seconds.")

    if duration_sec <= 0 or duration_sec > 1800:
        return bad_request(start_response, "Summary length must be between 1 and 1800 seconds.")

    prompt_text = form.getfirst("prompt", "").strip()

    filename = safe_filename(video_field.filename)
    job_id = create_job(int(user["id"]), filename, duration_sec)
    clip_token = secrets.token_hex(8)
    upload_dir = UPLOADS_DIR / f"user_{int(user['id'])}" / clip_token
    generated_dir = GENERATED_DIR / f"user_{int(user['id'])}" / clip_token
    upload_path = upload_dir / filename

    try:
        save_uploaded_video(video_field, upload_path)
    except Exception as exc:
        update_job(job_id, status="failed", message="Upload failed.", error=str(exc))
        return json_response(
            start_response,
            {"ok": False, "error": f"Upload failed: {exc}"},
            status="500 Internal Server Error",
        )

    worker = threading.Thread(
        target=run_clip_job,
        args=(job_id, int(user["id"]), filename, duration_sec, upload_path, generated_dir, prompt_text),
        daemon=True,
    )
    worker.start()

    return json_response(
        start_response,
        {"ok": True, "job_id": job_id},
        status="202 Accepted",
    )


def handle_job_status(environ, start_response, job_id: str):
    user = current_user(environ)
    if not user:
        return unauthorized(start_response)

    job = get_job(job_id)
    if not job or int(job["user_id"]) != int(user["id"]):
        return json_response(start_response, {"ok": False, "error": "Job not found."}, status="404 Not Found")

    return json_response(start_response, {"ok": True, "job": public_job_payload(job)})


def handle_download(environ, start_response, clip_id: int):
    user = current_user(environ)
    if not user:
        return redirect(start_response, "/auth?mode=login")

    clip = get_clip_for_user(int(user["id"]), clip_id)
    if not clip:
        return not_found(start_response, "Clip not found")

    file_path = media_path(clip["output_relative_path"])
    if not file_path:
        return not_found(start_response, "Clip not found")

    download_name = f"sliver-{Path(clip['source_name']).stem}.mp4"
    return file_response(environ, start_response, file_path, download_name=download_name)


def application(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    route_method = "GET" if method == "HEAD" else method
    path = unquote(environ.get("PATH_INFO", "/"))

    if path.startswith("/static/"):
        asset = static_path(path.removeprefix("/static/"))
        if not asset:
            return not_found(start_response)
        return file_response(environ, start_response, asset)

    if path.startswith("/assets/"):
        asset = assets_path(path.removeprefix("/assets/"))
        if not asset:
            return not_found(start_response)
        return file_response(environ, start_response, asset)

    if path.startswith("/media/"):
        asset = media_path(path.removeprefix("/media/"))
        if not asset:
            return not_found(start_response)
        return file_response(environ, start_response, asset)

    if route_method == "GET" and path == "/":
        return handle_home(environ, start_response)

    if route_method == "GET" and path == "/auth":
        return handle_auth_get(environ, start_response)

    if route_method == "POST" and path == "/auth/signup":
        return handle_signup(environ, start_response)

    if route_method == "POST" and path == "/auth/login":
        return handle_login(environ, start_response)

    if route_method == "POST" and path == "/auth/logout":
        return handle_logout(start_response)

    if route_method == "GET" and path == "/workspace":
        return handle_workspace(environ, start_response)

    if route_method == "GET" and path == "/profile":
        return handle_profile(environ, start_response)

    if route_method == "POST" and path == "/api/process":
        return handle_process(environ, start_response)

    if route_method == "GET" and path.startswith("/api/jobs/"):
        job_id = path.removeprefix("/api/jobs/").strip("/")
        if job_id:
            return handle_job_status(environ, start_response, job_id)

    if route_method == "GET" and path.startswith("/clips/") and path.endswith("/download"):
        clip_id_text = path.removeprefix("/clips/").removesuffix("/download").strip("/")
        if clip_id_text.isdigit():
            return handle_download(environ, start_response, int(clip_id_text))

    return respond(start_response, "404 Not Found", "Page not found")


def main():
    ensure_storage()
    host = os.environ.get("SLIVER_HOST", "127.0.0.1")
    port = int(os.environ.get("SLIVER_PORT", "8000"))
    with make_server(host, port, application) as server:
        print(f"Sliver running on http://{host}:{port}")
        server.serve_forever()


if __name__ == "__main__":
    main()
