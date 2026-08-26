#!/usr/bin/env python3
"""Static site server with a small SQLite-backed media API."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import quote, unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATABASE_PATH = DATA_DIR / "content.sqlite3"
PASSWORD_PATH = DATA_DIR / "admin-password.txt"
MAX_IMAGE_SIZE = 12 * 1024 * 1024
SESSION_COOKIE = "gusi_admin_session"
SESSION_LIFETIME = 8 * 60 * 60
ADMIN_PASSWORD = ""
SESSIONS: dict[str, float] = {}
SESSION_LOCK = Lock()
ALLOWED_SLOTS = {
    "hero-object",
    "program-clay",
    "program-face",
    "program-paint",
    "program-photo",
    "process-main",
    "result-one",
    "result-two",
    "result-three",
}


def connect_database() -> sqlite3.Connection:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect_database() as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS media (
                slot TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                mime_type TEXT NOT NULL,
                content BLOB NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )


def initialize_admin_password() -> tuple[str, bool]:
    configured_password = os.environ.get("GUSI_ADMIN_PASSWORD", "").strip()
    if configured_password:
        return configured_password, False
    if PASSWORD_PATH.exists():
        stored_password = PASSWORD_PATH.read_text(encoding="utf-8").strip()
        if stored_password:
            return stored_password, False

    generated_password = secrets.token_urlsafe(14)
    PASSWORD_PATH.write_text(f"{generated_password}\n", encoding="utf-8")
    PASSWORD_PATH.chmod(0o600)
    return generated_password, True


def detect_image_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


class WorkshopHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        path = urlparse(self.path).path
        if path.startswith("/api/") or path.endswith((".html", ".js", ".css")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(
        self,
        status: HTTPStatus,
        payload: dict | list,
        extra_headers: list[tuple[str, str]] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def get_session_token(self) -> str | None:
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def is_admin(self) -> bool:
        token = self.get_session_token()
        if not token:
            return False
        now = time.time()
        with SESSION_LOCK:
            expires_at = SESSIONS.get(token)
            if expires_at is None:
                return False
            if expires_at <= now:
                SESSIONS.pop(token, None)
                return False
            SESSIONS[token] = now + SESSION_LIFETIME
        return True

    def require_admin_api(self) -> bool:
        if self.is_admin():
            return True
        self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Требуется вход для персонала."})
        return False

    def parse_media_slot(self) -> str | None:
        path = urlparse(self.path).path
        prefix = "/api/media/"
        if not path.startswith(prefix):
            return None
        slot = unquote(path[len(prefix) :]).strip("/")
        return slot if slot in ALLOWED_SLOTS else None

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith(("/data/", "/sources/", "/.")) or path in {"/server.py", "/AGENTS.md"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if path in {"/admin.html", "/admin.js", "/admin.css"} and not self.is_admin():
            self.send_redirect(f"/login.html?next={quote(path)}")
            return
        if path == "/login.html" and self.is_admin():
            self.send_redirect("/admin.html")
            return
        if path == "/api/health":
            self.send_json(HTTPStatus.OK, {"status": "ok", "storage": "sqlite"})
            return
        if path == "/api/admin/session":
            if not self.require_admin_api():
                return
            self.send_json(HTTPStatus.OK, {"authenticated": True})
            return
        if path == "/api/media":
            if not self.require_admin_api():
                return
            with connect_database() as connection:
                rows = connection.execute(
                    "SELECT slot, file_name, mime_type, updated_at FROM media ORDER BY slot"
                ).fetchall()
            self.send_json(HTTPStatus.OK, [dict(row) for row in rows])
            return
        if path.startswith("/api/media/"):
            slot = self.parse_media_slot()
            if slot is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Неизвестный слот изображения."})
                return
            with connect_database() as connection:
                row = connection.execute(
                    "SELECT file_name, mime_type, content, updated_at FROM media WHERE slot = ?",
                    (slot,),
                ).fetchone()
            if row is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Для слота используется исходное изображение."})
                return
            content = bytes(row["content"])
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", row["mime_type"])
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-File-Name", quote(row["file_name"]))
            self.send_header("X-Updated-At", row["updated_at"])
            self.end_headers()
            self.wfile.write(content)
            return
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/admin/login":
            self.handle_admin_login()
            return
        if path == "/api/admin/logout":
            self.handle_admin_logout()
            return
        if not self.require_admin_api():
            return

        slot = self.parse_media_slot()
        if slot is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Неизвестный слот изображения."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length <= 0:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Файл не получен."})
            return
        if content_length > MAX_IMAGE_SIZE:
            self.close_connection = True
            self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Изображение больше 12 МБ."})
            return

        content = self.rfile.read(content_length)
        mime_type = detect_image_type(content)
        if mime_type is None:
            self.send_json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Разрешены только JPG, PNG и WebP."})
            return

        raw_name = self.headers.get("X-File-Name", "image")
        file_name = Path(unquote(raw_name)).name[:180] or "image"
        updated_at = datetime.now(timezone.utc).isoformat()

        with connect_database() as connection:
            connection.execute(
                """
                INSERT INTO media (slot, file_name, mime_type, content, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(slot) DO UPDATE SET
                    file_name = excluded.file_name,
                    mime_type = excluded.mime_type,
                    content = excluded.content,
                    updated_at = excluded.updated_at
                """,
                (slot, file_name, mime_type, content, updated_at),
            )

        self.send_json(
            HTTPStatus.OK,
            {"slot": slot, "fileName": file_name, "mimeType": mime_type, "updatedAt": updated_at},
        )

    def do_DELETE(self) -> None:  # noqa: N802
        if not self.require_admin_api():
            return
        slot = self.parse_media_slot()
        if slot is None:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Неизвестный слот изображения."})
            return
        with connect_database() as connection:
            connection.execute("DELETE FROM media WHERE slot = ?", (slot,))
        self.send_json(HTTPStatus.OK, {"slot": slot, "removed": True})

    def handle_admin_login(self) -> None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос входа."})
            return

        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос входа."})
            return

        password = payload.get("password", "") if isinstance(payload, dict) else ""
        if not isinstance(password, str) or not secrets.compare_digest(password, ADMIN_PASSWORD):
            time.sleep(0.25)
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Неверный пароль."})
            return

        token = secrets.token_urlsafe(32)
        with SESSION_LOCK:
            SESSIONS[token] = time.time() + SESSION_LIFETIME
        cookie = (
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict; "
            f"Max-Age={SESSION_LIFETIME}"
        )
        self.send_json(
            HTTPStatus.OK,
            {"authenticated": True},
            [("Set-Cookie", cookie)],
        )

    def handle_admin_logout(self) -> None:
        token = self.get_session_token()
        if token:
            with SESSION_LOCK:
                SESSIONS.pop(token, None)
        self.send_json(
            HTTPStatus.OK,
            {"authenticated": False},
            [("Set-Cookie", f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0")],
        )

    def log_message(self, format: str, *args) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> None:
    global ADMIN_PASSWORD
    parser = argparse.ArgumentParser(description="Serve the Гуси-Лебеди site with SQLite media storage.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4173)
    arguments = parser.parse_args()

    initialize_database()
    ADMIN_PASSWORD, generated_password = initialize_admin_password()
    server = ThreadingHTTPServer((arguments.host, arguments.port), WorkshopHandler)
    print(f"Гуси-Лебеди: http://{arguments.host}:{arguments.port}")
    print(f"SQLite: {DATABASE_PATH}")
    if generated_password:
        print(f"Создан пароль персонала: {ADMIN_PASSWORD}")
    else:
        print(f"Пароль персонала: {PASSWORD_PATH if not os.environ.get('GUSI_ADMIN_PASSWORD') else 'из переменной окружения'}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
