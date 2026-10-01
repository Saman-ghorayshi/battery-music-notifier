# battery_notifier/sms_client.py
"""SmsClient -- the laptop-side message store and gateway client.

SQLite is the UI source of truth; the gateway backfills and pushes events;
the store upserts idempotently by (backend, sms_id). Transport-agnostic:
a Backend object supplies hello/backfill/events/send/mark_read/delete.

The redaction engine runs on EVERYTHING before it is returned to any
consumer that transmits (AI digest, relay, logs) -- see sms_gateway.
"""
from __future__ import annotations

import json
import logging
import socket
import sqlite3
import struct
import threading
import time
import uuid
from pathlib import Path

from .redact import redact

log = logging.getLogger(__name__)

PROTO_VERSION = 1
PORT = 8100
FRAME_HEADER = 4  # big-endian u32 length prefix


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

class SmsStore:
    """SQLite persistence for the Messages tab."""

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS contacts(
      number TEXT PRIMARY KEY, name TEXT);
    CREATE TABLE IF NOT EXISTS threads(
      thread_id INTEGER PRIMARY KEY, number TEXT,
      last_ts INTEGER, unread INTEGER DEFAULT 0, snippet TEXT, backend TEXT);
    CREATE TABLE IF NOT EXISTS messages(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      backend TEXT NOT NULL, sms_id INTEGER NOT NULL,
      thread_id INTEGER, address TEXT, date INTEGER, date_sent INTEGER,
      type TEXT, read INTEGER, sub_id INTEGER, body TEXT,
      UNIQUE(backend, sms_id));
    CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id, date);
    CREATE INDEX IF NOT EXISTS idx_msg_unread ON messages(read) WHERE read = 0;
    CREATE TABLE IF NOT EXISTS calls(
      id INTEGER PRIMARY KEY AUTOINCREMENT, number TEXT, name TEXT,
      ts INTEGER, kind TEXT);
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """

    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(self.SCHEMA)
        self._lock = threading.Lock()

    def upsert_messages(self, backend: str, msgs: list[dict]) -> int:
        """Idempotent insert; returns count of NEW rows."""
        added = 0
        with self._lock:
            cur = self.db.cursor()
            for m in msgs or []:
                try:
                    cur.execute(
                        "SELECT id FROM messages WHERE backend=? AND sms_id=?",
                        (backend, m.get("sms_id")),
                    )
                    if cur.fetchone():
                        continue
                    cur.execute(
                        "INSERT INTO messages(backend,sms_id,thread_id,address,"
                        "date,date_sent,type,read,sub_id,body) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (backend, m.get("sms_id"), m.get("thread_id"),
                         m.get("address"), m.get("date", 0),
                         m.get("date_sent", 0), m.get("type", "in"),
                         1 if m.get("read") else 0, m.get("sub_id", 0),
                         m.get("body", "")),
                    )
                    added += 1
                except Exception as e:
                    log.warning("upsert skipped: %s", e)
            self.db.commit()
        return added

    def threads(self) -> list[dict]:
        with self._lock:
            rows = self.db.execute(
                "SELECT t.thread_id, t.number, t.last_ts, t.unread, t.snippet, "
                "COALESCE(c.name, '') AS name FROM threads t "
                "LEFT JOIN contacts c ON c.number = t.number "
                "ORDER BY t.last_ts DESC").fetchall()
        return [dict(r) for r in rows]

    def unread_first(self) -> list[dict]:
        """The Triage view: unread newest-first, then read newest-first."""
        with self._lock:
            rows = self.db.execute(
                "SELECT m.*, COALESCE(c.name,'') AS name FROM messages m "
                "LEFT JOIN contacts c ON c.number = m.address "
                "WHERE m.type IN ('in','out') ORDER BY m.read ASC, m.date DESC "
                "LIMIT 200").fetchall()
        return [dict(r) for r in rows]

    def mark_read(self, sms_ids: list[int]) -> None:
        with self._lock:
            self.db.executemany(
                "UPDATE messages SET read=1 WHERE id=?",
                [(i,) for i in sms_ids])
            self.db.commit()

    def meta_get(self, key: str) -> str | None:
        row = self.db.execute(
            "SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def meta_set(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO meta(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value))
            self.db.commit()


# ---------------------------------------------------------------------------
# framing
# ---------------------------------------------------------------------------

def send_frame(sock: socket.socket, obj: dict) -> None:
    data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock: socket.socket) -> dict | None:
    hdr = _recv_exact(sock, FRAME_HEADER)
    if hdr is None:
        return None
    (length,) = struct.unpack(">I", hdr)
    if length > 1 << 20:
        raise ValueError(f"frame too large: {length}")
    raw = _recv_exact(sock, length)
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))


def _recv_exact(sock: socket.socket, n: int) -> bytes | None:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return buf


# ---------------------------------------------------------------------------
# gateway client (laptop side)
# ---------------------------------------------------------------------------

class SmsGatewayClient:
    """Connects to a backend (phone mirror / modem dock) on the LAN,
    performs HELLO capability exchange, backfill-with-high-water-mark,
    and delivers live events to a callback. Reconnect + resync built in."""

    def __init__(self, store: SmsStore, host: str, port: int = PORT):
        self.store = store
        self.host = host
        self.port = port
        self.caps: dict | None = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    def connect(self) -> dict:
        self._sock = socket.create_connection((self.host, self.port), timeout=8)
        hello = {"t": "hello", "proto": PROTO_VERSION, "role": "client"}
        send_frame(self._sock, hello)
        resp = recv_frame(self._sock)
        self.caps = (resp or {}).get("caps", {})
        log.info("gateway hello: caps=%s", self.caps)
        return self.caps or {}

    def request_backfill(self, since: int = 0, limit: int = 500,
                         on_event=None) -> int:
        """Drain backfill pages; sms.event frames that arrive interleaved
        are forwarded to on_event (they belong to the live stream)."""
        send_frame(self._sock, {"t": "sms.backfill.req", "since": since, "limit": limit})
        added_total = 0
        while True:
            frame = recv_frame(self._sock)
            if frame is None or frame.get("t") != "sms.backfill.resp":
                if frame is not None and on_event:
                    on_event({"kind": frame.get("t"), "frame": frame})
                break
            added_total += self.store.upsert_messages(
                frame.get("backend", "unknown"), frame.get("msgs", []))
            if frame.get("page", 1) >= frame.get("pages", 1):
                break
        return added_total

    def listen_events(self, on_event) -> None:
        """Blocking loop delivering sms.event / call.event to a callback."""
        while not self._stop.is_set():
            try:
                frame = recv_frame(self._sock)
                if frame is None:
                    raise ConnectionError("gateway closed")
                t = frame.get("t", "")
                if t == "sms.event":
                    added = self.store.upsert_messages(
                        frame.get("backend", "unknown"), [frame.get("msg", {})])
                    on_event({"kind": "sms", "added": added, "frame": frame})
                elif t == "call.event":
                    on_event({"kind": "call", "frame": frame})
                elif t == "ping":
                    send_frame(self._sock, {"t": "pong"})
            except TimeoutError:
                # A quiet gateway with no events: normal, keep waiting.
                continue
            except (ConnectionError, OSError, ValueError) as e:
                log.warning("gateway event stream lost: %s", e)
                return

    def send(self, to: str, body: str) -> str:
        ref = uuid.uuid4().hex
        send_frame(self._sock, {"t": "sms.send.req", "ref": ref, "to": to,
                                "body": redact(body)["safe_text"]})
        return ref

    def mark_read(self, sms_ids: list[int]) -> None:
        if self.caps and self.caps.get("mark_read"):
            send_frame(self._sock, {"t": "sms.mark_read", "ids": sms_ids})
        self.store.mark_read(sms_ids)

    def close(self) -> None:
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------

log = logging.getLogger(__name__)
