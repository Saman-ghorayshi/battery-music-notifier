#!/usr/bin/env python3
"""Cross-OS local-socket thief protocol test (raw ACK protocol, no audio).

server role: bind 0.0.0.0:<port>, run the REAL NotificationServer handler in
a thread with a silent player, exit when the expected command lands.
client role: ping_server + send_command_with_ack(THIEF_ALERT), assert ACK.

    python tests/cross_os_socket.py server <port> <expected_cmd>
    python tests/cross_os_socket.py client <host> <port> <cmd>
"""
import sys
import threading
import time


def main():
    role = sys.argv[1]

    if role == "server":
        port = int(sys.argv[2])
        expected = sys.argv[3]
        from battery_notifier.config import Config
        from battery_notifier.remote import NotificationServer

        cfg = Config()
        cfg.music_files = []          # silent: play() no-ops on empty list
        cfg.socket_secret = ""
        srv = NotificationServer(cfg, "0.0.0.0", port, conn_mode="local")

        got = threading.Event()
        original = srv._handle_client

        def spy(conn, addr):
            import io
            import contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                original(conn, addr)
            out = buf.getvalue()
            if expected in out:
                got.set()

        srv._handle_client = spy

        # replicate run()'s socket loop but bounded: exit once expected seen
        import socket as _s
        sock = _s.socket(_s.AF_INET, _s.SOCK_STREAM)
        sock.setsockopt(_s.SOL_SOCKET, _s.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(4)
        sock.settimeout(20)
        print(f"SOCKET-SERVER ready on :{port} expecting {expected}", flush=True)
        end_at = time.time() + 20
        while time.time() < end_at and not got.is_set():
            try:
                conn, addr = sock.accept()
            except _s.timeout:
                break
            t = threading.Thread(target=srv._handle_client, args=(conn, addr), daemon=True)
            t.start()
            # give the handler a moment, then drop the connection
            t.join(timeout=3)
            try:
                conn.close()
            except Exception:
                pass
        sock.close()
        if got.is_set():
            print(f"RESULT: PASS -- {expected} received and ACKed")
            sys.exit(0)
        print("RESULT: timeout")
        sys.exit(2)

    # ---- client ----
    host, port, cmd = sys.argv[2], int(sys.argv[3]), sys.argv[4]
    from battery_notifier.connection import ping_server, send_command_with_ack

    if not ping_server(host, port, timeout=3.0):
        print("RESULT: no PONG -- server unreachable from this OS")
        sys.exit(3)
    ok = send_command_with_ack(host, port, cmd, timeout=5.0, secret="")
    print(f"RESULT: {'PASS' if ok else 'FAIL'} -- ACK for {cmd}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
