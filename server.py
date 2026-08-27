#!/usr/bin/env python3
"""Static site server with a small SQLite-backed media API."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
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
LOCAL_TIMEZONE = timezone(timedelta(hours=5))  # Тюмень
TOKEN_PATTERN = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")
CHAT_ID_PATTERN = re.compile(r"^(-?\d{1,32}|@[A-Za-z0-9_]{4,32})$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")
BOOKING_MAX_PER_WINDOW = 5
BOOKING_WINDOW = 10 * 60
BOOKING_HISTORY: dict[str, list[float]] = {}
BOOKING_LOCK = Lock()
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
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                name TEXT NOT NULL,
                phone TEXT NOT NULL,
                format TEXT NOT NULL,
                event_date TEXT NOT NULL,
                guests TEXT NOT NULL,
                comment TEXT NOT NULL,
                delivery TEXT NOT NULL
            )
            """
        )


def read_setting(key: str) -> str:
    with connect_database() as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else ""


def write_setting(key: str, value: str) -> None:
    with connect_database() as connection:
        connection.execute(
            """
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def telegram_credentials() -> tuple[str, str]:
    """Переменные окружения имеют приоритет, иначе берём то, что сохранено в админке."""
    token = os.environ.get("GUSI_TELEGRAM_TOKEN", "").strip() or read_setting("telegram_token")
    chat_id = os.environ.get("GUSI_TELEGRAM_CHAT_ID", "").strip() or read_setting("telegram_chat_id")
    return token, chat_id


def telegram_request(token: str, method: str, payload: dict | None = None) -> dict:
    if not TOKEN_PATTERN.match(token):
        return {"ok": False, "description": "Токен выглядит неправильно."}

    url = f"https://api.telegram.org/bot{token}/{method}"
    data = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        try:
            return json.loads(error.read())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"ok": False, "description": f"Telegram ответил {error.code}"}
    except Exception as error:  # сеть, DNS, таймаут, кодировка — заявка важнее аккуратного типа
        return {"ok": False, "description": f"Нет связи с Telegram: {error}"}


def brevo_credentials() -> tuple[str, str, str]:
    key = os.environ.get("GUSI_BREVO_API_KEY", "").strip() or read_setting("brevo_api_key")
    sender = os.environ.get("GUSI_BREVO_SENDER", "").strip() or read_setting("brevo_sender")
    recipient = os.environ.get("GUSI_BREVO_RECIPIENT", "").strip() or read_setting("brevo_recipient")
    return key, sender, recipient


def brevo_send(key: str, sender: str, recipient: str, subject: str, html_body: str) -> dict:
    payload = {
        "sender": {"name": "Сайт Гуси-Лебеди", "email": sender},
        "to": [{"email": recipient}],
        "subject": subject,
        "htmlContent": html_body,
    }
    request = urllib.request.Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "api-key": key, "accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
            return {"ok": True}
    except urllib.error.HTTPError as error:
        try:
            details = json.loads(error.read())
            message = details.get("message") or details.get("code") or f"Brevo ответил {error.code}"
        except (json.JSONDecodeError, UnicodeDecodeError):
            message = f"Brevo ответил {error.code}"
        return {"ok": False, "description": message}
    except Exception as error:  # сеть, DNS, таймаут — письмо не важнее самой заявки
        return {"ok": False, "description": f"Нет связи с Brevo: {error}"}


def build_booking_email(booking: dict) -> str:
    rows = [
        ("Имя", booking["name"]),
        ("Телефон", booking["phone"]),
        ("Формат", booking["format"]),
        ("Дата", format_booking_date(booking["date"])),
        ("Человек", booking["guests"]),
    ]
    if booking["comment"]:
        rows.append(("Комментарий", booking["comment"]))

    cells = "".join(
        f'<tr><td style="padding:6px 16px 6px 0;color:#666;white-space:nowrap;vertical-align:top">{escape(label)}</td>'
        f'<td style="padding:6px 0"><b>{escape(value)}</b></td></tr>'
        for label, value in rows
    )
    stamp = datetime.now(LOCAL_TIMEZONE).strftime("%d.%m.%Y, %H:%M")
    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:15px;color:#161513">'
        "<h2 style=\"margin:0 0 18px\">Новая заявка с сайта</h2>"
        f'<table style="border-collapse:collapse">{cells}</table>'
        f'<p style="margin:22px 0 0;color:#888;font-size:13px">Отправлено {escape(stamp)}</p>'
        "</div>"
    )


def deliver_booking(booking: dict) -> dict:
    """Каждый канал отправляется отдельно: сбой одного не мешает другому."""
    results: dict[str, str] = {}

    token, chat_id = telegram_credentials()
    if token and chat_id:
        outcome = telegram_request(
            token,
            "sendMessage",
            {
                "chat_id": chat_id,
                "text": build_booking_message(booking),
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
        results["telegram"] = "ok" if outcome.get("ok") else f"ошибка: {outcome.get('description')}"

    key, sender, recipient = brevo_credentials()
    if key and sender and recipient:
        outcome = brevo_send(key, sender, recipient, "Новая заявка с сайта", build_booking_email(booking))
        results["email"] = "ok" if outcome.get("ok") else f"ошибка: {outcome.get('description')}"

    return results


def store_booking(booking: dict, delivery: dict) -> None:
    with connect_database() as connection:
        connection.execute(
            """
            INSERT INTO bookings (created_at, name, phone, format, event_date, guests, comment, delivery)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(LOCAL_TIMEZONE).isoformat(timespec="seconds"),
                booking["name"],
                booking["phone"],
                booking["format"],
                booking["date"],
                booking["guests"],
                booking["comment"],
                json.dumps(delivery, ensure_ascii=False),
            ),
        )


def booking_rate_limit_exceeded(client: str) -> bool:
    now = time.time()
    with BOOKING_LOCK:
        history = [stamp for stamp in BOOKING_HISTORY.get(client, []) if now - stamp < BOOKING_WINDOW]
        if len(history) >= BOOKING_MAX_PER_WINDOW:
            BOOKING_HISTORY[client] = history
            return True
        history.append(now)
        BOOKING_HISTORY[client] = history
    return False


def clean_booking_field(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip()[:limit]


def format_booking_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d.%m.%Y")
    except ValueError:
        return value


def build_booking_message(booking: dict) -> str:
    lines = [
        "<b>🎉 Новая заявка с сайта</b>",
        "",
        f"<b>Имя:</b> {escape(booking['name'])}",
        f"<b>Телефон:</b> {escape(booking['phone'])}",
        f"<b>Формат:</b> {escape(booking['format'])}",
        f"<b>Дата:</b> {escape(format_booking_date(booking['date']))}",
        f"<b>Человек:</b> {escape(booking['guests'])}",
    ]
    if booking["comment"]:
        lines.append(f"<b>Комментарий:</b> {escape(booking['comment'])}")
    stamp = datetime.now(LOCAL_TIMEZONE).strftime("%d.%m.%Y, %H:%M")
    lines += ["", f"<i>Отправлено {stamp}</i>"]
    return "\n".join(lines)


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

    def read_json_body(self, limit: int = 8192) -> dict | None:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > limit:
            return None
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def client_key(self) -> str:
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

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
        if path == "/api/admin/telegram":
            if not self.require_admin_api():
                return
            token, chat_id = telegram_credentials()
            self.send_json(
                HTTPStatus.OK,
                {
                    "configured": bool(token and chat_id),
                    "chatId": chat_id,
                    "tokenHint": f"…{token[-6:]}" if token else "",
                    "fromEnvironment": bool(os.environ.get("GUSI_TELEGRAM_TOKEN", "").strip()),
                },
            )
            return
        if path == "/api/admin/email":
            if not self.require_admin_api():
                return
            key, sender, recipient = brevo_credentials()
            self.send_json(
                HTTPStatus.OK,
                {
                    "configured": bool(key and sender and recipient),
                    "sender": sender,
                    "recipient": recipient,
                    "keyHint": f"…{key[-6:]}" if key else "",
                    "fromEnvironment": bool(os.environ.get("GUSI_BREVO_API_KEY", "").strip()),
                },
            )
            return
        if path == "/api/admin/bookings":
            if not self.require_admin_api():
                return
            with connect_database() as connection:
                rows = connection.execute(
                    """
                    SELECT id, created_at, name, phone, format, event_date, guests, comment, delivery
                    FROM bookings ORDER BY id DESC LIMIT 100
                    """
                ).fetchall()
            bookings = []
            for row in rows:
                item = dict(row)
                try:
                    item["delivery"] = json.loads(item["delivery"])
                except (json.JSONDecodeError, TypeError):
                    item["delivery"] = {}
                bookings.append(item)
            self.send_json(HTTPStatus.OK, bookings)
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
        if path == "/api/booking":
            self.handle_booking()
            return
        if not self.require_admin_api():
            return
        if path == "/api/admin/telegram":
            self.handle_telegram_settings()
            return
        if path == "/api/admin/email":
            self.handle_email_settings()
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

    def handle_booking(self) -> None:
        if booking_rate_limit_exceeded(self.client_key()):
            self.send_json(
                HTTPStatus.TOO_MANY_REQUESTS,
                {"error": "Слишком много заявок подряд. Попробуйте через несколько минут."},
            )
            return

        payload = self.read_json_body()
        if payload is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректная заявка."})
            return

        booking = {
            "name": clean_booking_field(payload.get("name"), 100),
            "phone": clean_booking_field(payload.get("phone"), 40),
            "format": clean_booking_field(payload.get("format"), 100),
            "date": clean_booking_field(payload.get("date"), 20),
            "guests": clean_booking_field(payload.get("guests"), 10),
            "comment": clean_booking_field(payload.get("comment"), 1000),
        }

        digits = re.sub(r"\D", "", booking["phone"])
        required = all(booking[field] for field in ("name", "phone", "format", "date", "guests"))
        if not required or len(digits) < 10:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Заполнены не все поля заявки."})
            return

        # Сначала сохраняем: даже если все каналы отвалятся, заявка не пропадёт.
        delivery = deliver_booking(booking)
        store_booking(booking, delivery)

        for channel, outcome in delivery.items():
            if outcome != "ok":
                print(f"[заявка] {channel}: {outcome}")

        if not delivery:
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "Приём заявок ещё не настроен. Напишите нам, пожалуйста, в VK."},
            )
            return

        if not any(outcome == "ok" for outcome in delivery.values()):
            self.send_json(
                HTTPStatus.BAD_GATEWAY,
                {"error": "Не удалось отправить заявку. Напишите нам, пожалуйста, в VK."},
            )
            return

        self.send_json(HTTPStatus.OK, {"delivered": True})

    def handle_telegram_settings(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос."})
            return

        token = clean_booking_field(payload.get("token"), 120)
        chat_id = clean_booking_field(payload.get("chatId"), 40)
        if not token or not chat_id:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Нужны и токен, и chat id."})
            return
        if not TOKEN_PATTERN.match(token):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Токен не похож на настоящий. Скопируйте его целиком из @BotFather."},
            )
            return
        if not CHAT_ID_PATTERN.match(chat_id):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Chat id — это число (у групп со знаком минус) или @имя канала."},
            )
            return

        check = telegram_request(token, "getMe")
        if not check.get("ok"):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"Telegram не принял токен: {check.get('description', 'неизвестная ошибка')}"},
            )
            return

        probe = telegram_request(
            token,
            "sendMessage",
            {"chat_id": chat_id, "text": "✅ Приём заявок с сайта настроен. Сюда будут приходить заявки."},
        )
        if not probe.get("ok"):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"Токен верный, но в этот чат бот писать не может: {probe.get('description', '')}"},
            )
            return

        write_setting("telegram_token", token)
        write_setting("telegram_chat_id", chat_id)
        self.send_json(
            HTTPStatus.OK,
            {"configured": True, "botName": check["result"].get("username", ""), "chatId": chat_id},
        )

    def handle_email_settings(self) -> None:
        payload = self.read_json_body()
        if payload is None:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Некорректный запрос."})
            return

        key = clean_booking_field(payload.get("apiKey"), 200)
        sender = clean_booking_field(payload.get("sender"), 120).lower()
        recipient = clean_booking_field(payload.get("recipient"), 120).lower()

        if not key or not sender or not recipient:
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "Нужны ключ Brevo, адрес отправителя и адрес получателя."},
            )
            return
        for address, label in ((sender, "отправителя"), (recipient, "получателя")):
            if not EMAIL_PATTERN.match(address):
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": f"Адрес {label} выглядит неправильно."})
                return

        probe = brevo_send(
            key,
            sender,
            recipient,
            "Проверка: заявки с сайта",
            "<p>Это проверочное письмо. Заявки с сайта будут приходить сюда.</p>",
        )
        if not probe.get("ok"):
            self.send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": f"Brevo не принял письмо: {probe.get('description', 'неизвестная ошибка')}"},
            )
            return

        write_setting("brevo_api_key", key)
        write_setting("brevo_sender", sender)
        write_setting("brevo_recipient", recipient)
        self.send_json(HTTPStatus.OK, {"configured": True, "recipient": recipient})

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
