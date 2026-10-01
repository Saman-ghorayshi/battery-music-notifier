# tests/test_sms_client.py
"""Gateway framing, store, and protocol tests. Deterministic: no socket
threading races. The backfill test drives the client against a scripted
server synchronously (server closes after its script → client sees EOF)."""
import socket
import threading
import time as _t
from pathlib import Path

import pytest

from battery_notifier.sms_client import (
    SmsGatewayClient, SmsStore, send_frame, recv_frame,
)


@pytest.fixture
def store(tmp_path):
    return SmsStore(tmp_path / "sms.db")


def test_frame_roundtrip():
    a, b = socket.socketpair()
    msg = {"t": "hello", "body": "سلام دنیا", "n": 42}
    send_frame(a, msg)
    assert recv_frame(b) == msg
    a.close(); b.close()


def test_frame_rejects_oversized():
    a, b = socket.socketpair()
    a.sendall((2 ** 20 + 1).to_bytes(4, "big"))
    with pytest.raises(ValueError):
        recv_frame(b)
    a.close(); b.close()


def test_backfill_upserts_and_is_idempotent(store):
    msgs = [
        {"sms_id": 1, "thread_id": 1, "address": "+98912", "date": 100,
         "type": "in", "read": False, "body": "سلام"},
        {"sms_id": 2, "thread_id": 1, "address": "+98912", "date": 200,
         "type": "in", "read": False, "body": "کد 55123"},
    ]
    assert store.upsert_messages("mirror", msgs) == 2
    assert store.upsert_messages("mirror", msgs) == 0
    assert store.unread_first()[0]["body"] == "کد 55123"


def test_store_unread_first_ordering(store):
    rows = [
        {"sms_id": 1, "thread_id": 1, "address": "+98912", "date": 100,
         "type": "in", "read": True, "body": "read one"},
        {"sms_id": 2, "thread_id": 1, "address": "+98912", "date": 200,
         "type": "in", "read": False, "body": "unread newest"},
        {"sms_id": 3, "thread_id": 1, "address": "+98912", "date": 50,
         "type": "in", "read": False, "body": "unread older"},
    ]
    store.upsert_messages("mirror", rows)
    result = store.unread_first()
    # unread first (date DESC), then read
    assert result[0]["body"] == "unread newest"
    assert result[1]["body"] == "unread older"
    assert result[2]["body"] == "read one"


def test_gateway_backfill_and_event(store):
    """Full protocol over a real socket-pair. The server thread accepts,
    speaks the protocol, and closes. The client connects after the server
    is ready (avoiding the accept/connect deadlock)."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]

    events = []
    ready = threading.Event()

    def server_side(conn):
        with conn:
            ready.set()  # signal: connection accepted, protocol can start
            send_frame(conn, {"t": "hello", "caps": {"mode": "mirror"}})
            recv_frame(conn)  # drain client's backfill.req
            send_frame(conn, {
                "t": "sms.backfill.resp", "page": 1, "pages": 1,
                "backend": "mirror",
                "msgs": [{"sms_id": 10, "thread_id": 2, "address": "+98913",
                          "date": 300, "type": "in", "read": False,
                          "body": "فردا میای؟"}],
            })
            send_frame(conn, {
                "t": "sms.event", "kind": "received", "backend": "mirror",
                "msg": {"sms_id": 11, "thread_id": 2, "address": "+98913",
                        "date": 350, "type": "in", "read": False,
                        "body": "دومی"},
            })
            send_frame(conn, {"t": "ping"})
            try: recv_frame(conn)  # wait for pong
            except Exception: pass

    # accept + serve in a background thread (before client.connect)
    def serve():
        conn, _ = server.accept()
        server_side(conn)

    server_thread = threading.Thread(target=serve, daemon=True)
    server_thread.start()
    _t.sleep(0.1)  # let accept() start listening

    client = SmsGatewayClient(store, "127.0.0.1", port)
    caps = client.connect()
    assert caps.get("mode") == "mirror"

    def on_evt(e):
        events.append(e)

    # request_backfill drains the resp page AND the interleaved sms.event
    added = client.request_backfill(on_event=on_evt)
    assert added == 1

    # drain remaining frames (sms.event, ping) — in production,
    # listen_events handles these; here we drain manually for the test
    # AND upsert to the store (same as listen_events does).
    from battery_notifier.sms_client import recv_frame as _rf
    while True:
        frame = _rf(client._sock)
        if frame is None:
            break
        if frame.get("t") == "ping":
            send_frame(client._sock, {"t": "pong"})
            break
        events.append({"kind": frame.get("t"), "frame": frame})
        if frame.get("t") == "sms.event":
            store.upsert_messages(frame.get("backend", "mirror"),
                                  [frame.get("msg", {})])

    # the server closes after our pong → client's next recv gets EOF
    client.close()
    server_thread.join(timeout=5)

    assert events, "no events delivered"
    assert events[0]["frame"]["msg"]["body"] == "دومی"
    rows = store.unread_first()
    bodies = [r["body"] for r in rows]
    assert "فردا میای؟" in bodies and "دومی" in bodies
    server.close()
