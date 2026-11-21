"""SQLite metadata + file storage + ingest/validation. No web code here."""
import base64
import binascii
import contextvars
import ipaddress
import os
import socket
import sqlite3
import threading
import time
import urllib.parse
import uuid
from pathlib import Path

import httpx

DATA_DIR = Path(os.environ.get("INBOX_DATA_DIR", "/data"))
FILES_DIR = DATA_DIR / "files"
DB_PATH = DATA_DIR / "inbox.db"
MAX_BYTES = 50 * 1024 * 1024
TYPES = ("pdf", "markdown", "html", "text")
EXT = {"pdf": "pdf", "markdown": "md", "html": "html", "text": "txt"}
BY_EXT = {".pdf": "pdf", ".md": "markdown", ".markdown": "markdown",
          ".html": "html", ".htm": "html", ".txt": "text"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'general',
  source_agent TEXT NOT NULL DEFAULT 'unknown',
  summary TEXT,
  type TEXT NOT NULL,
  file_path TEXT NOT NULL,
  size INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0,
  done_at TEXT,
  project_id TEXT
);
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL COLLATE NOCASE UNIQUE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_state (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  last_used_at TEXT,
  revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS claims (
  id TEXT PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  used_at TEXT
);
CREATE INDEX IF NOT EXISTS items_done_created ON items(done, created_at DESC);
"""
_lock = threading.Lock()
# Name of the per-agent token that authenticated the current request (None for the admin token).
# When set it overrides any client-supplied source_agent.
CURRENT_AGENT: contextvars.ContextVar = contextvars.ContextVar("current_agent", default=None)


class PushError(Exception):
    """Validation failure; .status is the HTTP status the REST API should use."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def db() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init() -> None:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)
        columns = {r[1] for r in c.execute("PRAGMA table_info(items)")}
        if "project_id" not in columns:
            c.execute("ALTER TABLE items ADD COLUMN project_id TEXT")
        c.execute("CREATE INDEX IF NOT EXISTS items_project_created ON items(project_id, created_at DESC)")


def norm_category(v) -> str:
    v = " ".join(str(v or "").split()).lower()[:40]
    return v or "general"


def norm_project_name(v) -> str:
    name = " ".join(str(v or "").split())[:120]
    if not name:
        raise PushError(400, "project name is required")
    return name


def create_project(name) -> dict:
    project = {"id": uuid.uuid4().hex, "name": norm_project_name(name), "created_at": now()}
    try:
        with _lock, db() as c:
            c.execute("INSERT INTO projects(id,name,created_at) VALUES (?,?,?)",
                      (project["id"], project["name"], project["created_at"]))
    except sqlite3.IntegrityError:
        raise PushError(409, "a project with this name already exists")
    return project


def get_project(project_id: str) -> dict | None:
    with db() as c:
        r = c.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    return dict(r) if r else None


def list_projects() -> list[dict]:
    with db() as c:
        rows = c.execute("""SELECT p.id, p.name, p.created_at, COUNT(i.id) AS count,
                            COALESCE(SUM(i.done=0), 0) AS unread
                           FROM projects p LEFT JOIN items i ON i.project_id=p.id
                           GROUP BY p.id ORDER BY p.name COLLATE NOCASE""").fetchall()
    return [dict(r) for r in rows]


def delete_project(project_id: str) -> bool:
    with _lock, db() as c:
        c.execute("UPDATE items SET project_id=NULL WHERE project_id=?", (project_id,))
        return c.execute("DELETE FROM projects WHERE id=?", (project_id,)).rowcount > 0


def _project_id(project_id) -> str | None:
    if project_id is None or project_id == "":
        return None
    if not get_project(str(project_id)):
        raise PushError(400, "no such project")
    return str(project_id)


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def detect_type(data: bytes, filename: str | None, declared: str | None, from_text: bool) -> str:
    """Sniff the real type. PDFs are identified by magic bytes, never by extension."""
    declared = (declared or "").strip().lower() or None
    if declared and declared not in TYPES:
        raise PushError(415, f"unsupported type {declared!r}; use one of: {', '.join(TYPES)}")
    if b"%PDF-" in data[:1024]:
        if declared and declared != "pdf":
            raise PushError(415, f"content is a PDF but type={declared!r} was declared")
        return "pdf"
    if declared == "pdf" or os.path.splitext(filename or "")[1].lower() == ".pdf":
        raise PushError(415, "named/declared as PDF but content has no %PDF- magic bytes")
    if not _is_text(data):
        raise PushError(415, "unsupported content: not a PDF and not UTF-8 text")
    if declared:
        return declared
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in BY_EXT and BY_EXT[ext] != "pdf":
        return BY_EXT[ext]
    if not from_text:
        head = data[:2048].lstrip().lower()
        if head.startswith((b"<!doctype html", b"<html")):
            return "html"
    return "markdown"


def _block_private(host: str) -> None:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        raise PushError(400, f"cannot resolve {host}")
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise PushError(400, "url resolves to a non-public address; fetch refused")


def fetch_url(url: str) -> tuple[bytes, str]:
    """Download http(s) content (SSRF-guarded, size-capped, manual redirects)."""
    name = ""
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for _ in range(4):
            p = urllib.parse.urlsplit(url)
            if p.scheme not in ("http", "https") or not p.hostname:
                raise PushError(400, "url must be http(s)")
            _block_private(p.hostname)
            with client.stream("GET", url) as r:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                    url = urllib.parse.urljoin(url, r.headers["location"])
                    continue
                if r.status_code != 200:
                    raise PushError(400, f"url fetch failed: HTTP {r.status_code}")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise PushError(413, "file too large (limit 50 MB)")
                name = os.path.basename(p.path)
                return bytes(buf), name
    raise PushError(400, "too many redirects")


def add_item(*, title, category=None, data: bytes, filename=None, declared_type=None,
             summary=None, source_agent=None, project_id=None, from_text=False) -> dict:
    title = " ".join(str(title or "").split())[:300]
    if not title:
        raise PushError(400, "title is required")
    if not data:
        raise PushError(400, "empty content")
    if len(data) > MAX_BYTES:
        raise PushError(413, "file too large (limit 50 MB)")
    project_id = _project_id(project_id)
    typ = detect_type(data, filename, declared_type, from_text)
    item_id = uuid.uuid4().hex
    path = FILES_DIR / f"{item_id}.{EXT[typ]}"  # random name; user-supplied names never touch disk
    path.write_bytes(data)
    row = (item_id, title, norm_category(category),
           " ".join(str(CURRENT_AGENT.get() or source_agent or "").split())[:80] or "unknown",
           (str(summary).strip()[:1000] or None) if summary else None,
           typ, path.name, len(data), now(), project_id)
    with _lock, db() as c:
        c.execute("INSERT INTO items(id,title,category,source_agent,summary,type,file_path,size,created_at,project_id)"
                  " VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    return get_item(item_id)


def update_item(item_id, *, data: bytes, filename=None, declared_type=None, title=None, category=None,
                summary=None, project_id=None, from_text=False) -> dict:
    """Replace an item's content in place. Keeps id/link, done flag and saved page state."""
    it = get_item(item_id)
    if not it:
        raise PushError(404, "no such item")
    if not data:
        raise PushError(400, "empty content")
    if len(data) > MAX_BYTES:
        raise PushError(413, "file too large (limit 50 MB)")
    if project_id is not None:
        project_id = _project_id(project_id)
    typ = detect_type(data, filename, declared_type, from_text)
    path = FILES_DIR / f"{item_id}.{EXT[typ]}"
    path.write_bytes(data)
    if path.name != it["file_path"]:
        (FILES_DIR / it["file_path"]).unlink(missing_ok=True)
    new_title = " ".join(str(title or "").split())[:300] or it["title"]
    new_summary = (str(summary).strip()[:1000] or None) if summary else it["summary"]
    with _lock, db() as c:
        c.execute("UPDATE items SET title=?,category=?,summary=?,type=?,file_path=?,size=?,project_id=? WHERE id=?",
                  (new_title, norm_category(category) if category else it["category"], new_summary,
                   typ, path.name, len(data), project_id if project_id is not None else it["project_id"], item_id))
    return get_item(item_id)


def decode_b64(s: str) -> bytes:
    if len(s) > MAX_BYTES * 4 // 3 + 16:
        raise PushError(413, "file too large (limit 50 MB)")
    try:
        return base64.b64decode(s, validate=False)
    except (binascii.Error, ValueError):
        raise PushError(400, "content_base64 is not valid base64")


def get_item(item_id: str) -> dict | None:
    with db() as c:
        r = c.execute("SELECT items.*, projects.name AS project_name FROM items "
                      "LEFT JOIN projects ON projects.id=items.project_id WHERE items.id=?", (item_id,)).fetchone()
    return dict(r) if r else None


def list_items(status="unread", category=None, project_id=None, limit=50, offset=0, sort="recent") -> list[dict]:
    where, args = [], []
    if status == "unread":
        where.append("done=0")
    elif status == "done":
        where.append("done=1")
    elif status not in ("all", None, ""):
        raise PushError(400, "status must be unread, done or all")
    if category:
        where.append("category=?")
        args.append(norm_category(category))
    if project_id:
        where.append("project_id=?")
        args.append(str(project_id))
    order = "items.category ASC, items.created_at DESC" if sort == "category" else "items.created_at DESC, items.rowid DESC"
    sql = ("SELECT items.*, projects.name AS project_name FROM items "
           "LEFT JOIN projects ON projects.id=items.project_id" + (" WHERE " + " AND ".join(where) if where else ""))
    sql += f" ORDER BY {order} LIMIT ? OFFSET ?"
    with db() as c:
        return [dict(r) for r in c.execute(sql, (*args, max(1, min(int(limit), 500)), max(0, int(offset))))]


def categories(status="all") -> list[dict]:
    where = {"unread": "WHERE done=0", "done": "WHERE done=1"}.get(status, "")
    with db() as c:
        return [{"category": r[0], "count": r[1], "unread": r[2]} for r in c.execute(
            f"SELECT category, COUNT(*), SUM(done=0) FROM items {where} GROUP BY category ORDER BY category")]


def counts() -> dict:
    with db() as c:
        t, u = c.execute("SELECT COUNT(*), COALESCE(SUM(done=0),0) FROM items").fetchone()
    return {"all": t, "unread": u, "done": t - u}


def set_done(item_id: str, done: bool) -> dict | None:
    with _lock, db() as c:
        c.execute("UPDATE items SET done=?, done_at=? WHERE id=?",
                  (1 if done else 0, now() if done else None, item_id))
    return get_item(item_id)


def mark_all_done(category=None) -> int:
    sql, args = "UPDATE items SET done=1, done_at=? WHERE done=0", [now()]
    if category:
        sql += " AND category=?"
        args.append(norm_category(category))
    with _lock, db() as c:
        return c.execute(sql, args).rowcount


def delete_item(item_id: str) -> bool:
    it = get_item(item_id)
    if not it:
        return False
    with _lock, db() as c:
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
    (FILES_DIR / it["file_path"]).unlink(missing_ok=True)
    return True


def file_for(item: dict) -> Path:
    return FILES_DIR / item["file_path"]


MAX_STATE = 256 * 1024


def get_state(item_id: str) -> str:
    with db() as c:
        r = c.execute("SELECT data FROM item_state WHERE id=?", (item_id,)).fetchone()
    return r["data"] if r else "{}"


def set_state(item_id: str, data: str) -> None:
    with _lock, db() as c:
        c.execute("INSERT INTO item_state(id,data) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                  (item_id, data))
