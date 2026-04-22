from __future__ import annotations

import base64
import cgi
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sqlite3
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote
from wsgiref.simple_server import make_server
from wsgiref.util import FileWrapper

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "static"
TEMPLATES_DIR = ROOT_DIR / "templates"
DATA_DIR = ROOT_DIR / "web_data"
UPLOADS_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
DB_PATH = DATA_DIR / "sliver.sqlite3"

SESSION_COOKIE = "sliver_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30
PASSWORD_ITERATIONS = 200_000
DEFAULT_SECRET = "sliver-dev-secret"
SECRET_KEY = os.environ.get("SLIVER_SECRET_KEY", DEFAULT_SECRET).encode("utf-8")

JOBS: dict[str, dict[str, Any]] = {}
JOB_LOCK = threading.Lock()

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


def parse_multipart_form(environ) -> cgi.FieldStorage:
    return cgi.FieldStorage(fp=environ["wsgi.input"], environ=environ, keep_blank_values=True)


def parse_cookies(environ) -> dict[str, str]:
    cookie_header = environ.get("HTTP_COOKIE", "")
    cookies = {}
    for chunk in cookie_header.split(";"):
        if "=" not in chunk:
            continue
        key, value = chunk.strip().split("=", 1)
        cookies[key] = unquote(value)
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


def ensure_storage():
    for folder in (DATA_DIR, UPLOADS_DIR, GENERATED_DIR):
        folder.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(DB_PATH) as connection:
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
    job = {
        "id": job_id,
        "user_id": user_id,
        "source_name": source_name,
        "duration_sec": duration_sec,
        "status": "queued",
        "progress": 0,
        "message": "Upload received. Preparing your summary.",
        "clip": None,
        "error": None,
        "created_at": now_utc().isoformat(),
        "updated_at": now_utc().isoformat(),
    }
    with JOB_LOCK:
        JOBS[job_id] = job
    return job_id


def update_job(job_id: str, **changes):
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job.update(changes)
        job["updated_at"] = now_utc().isoformat()


def get_job(job_id: str) -> dict[str, Any] | None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return None
        return dict(job)


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
    resolved = (DATA_DIR / relative_path).resolve()
    if DATA_DIR.resolve() not in resolved.parents and resolved != DATA_DIR.resolve():
        return None
    return resolved


def static_path(relative_path: str) -> Path | None:
    resolved = (STATIC_DIR / relative_path).resolve()
    if STATIC_DIR.resolve() not in resolved.parents and resolved != STATIC_DIR.resolve():
        return None
    return resolved


def file_response(start_response, file_path: Path, download_name: str | None = None):
    if not file_path.exists() or not file_path.is_file():
        return not_found(start_response)

    mime_type, _ = mimetypes.guess_type(file_path.as_posix())
    headers = [
        ("Content-Type", mime_type or "application/octet-stream"),
        ("Content-Length", str(file_path.stat().st_size)),
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


def save_uploaded_video(file_item: cgi.FieldStorage, destination: Path):
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
            )
        ).resolve()
        relative_output = output_path.relative_to(DATA_DIR).as_posix()
        created_at = now_utc().isoformat()
        clip_id = insert_clip(
            user_id=user_id,
            source_name=filename,
            duration_sec=duration_sec,
            output_relative_path=relative_output,
            created_at=created_at,
        )
        clip_payload = build_clip_payload(
            clip_id=clip_id,
            source_name=filename,
            duration_sec=duration_sec,
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
        args=(job_id, int(user["id"]), filename, duration_sec, upload_path, generated_dir),
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
    return file_response(start_response, file_path, download_name=download_name)


def application(environ, start_response):
    ensure_storage()
    method = environ.get("REQUEST_METHOD", "GET").upper()
    route_method = "GET" if method == "HEAD" else method
    path = unquote(environ.get("PATH_INFO", "/"))

    if path.startswith("/static/"):
        asset = static_path(path.removeprefix("/static/"))
        if not asset:
            return not_found(start_response)
        return file_response(start_response, asset)

    if path.startswith("/media/"):
        asset = media_path(path.removeprefix("/media/"))
        if not asset:
            return not_found(start_response)
        return file_response(start_response, asset)

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
