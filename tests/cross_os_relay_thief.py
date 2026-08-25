#!/usr/bin/env python3
"""Cross-OS thief-sync over the REAL CF relay.

Run on the listening OS:
    python tests/cross_os_relay_thief.py listen <marker_file> [worker_url]
Run on the sending OS (a second later):
    python tests/cross_os_relay_thief.py send <marker_file> [worker_url]

The sender writes its send-time into the shared marker file (both OSes see
the same clock), the listener measures alert-arrival latency against it and
exits 0 when the alarm landed in under 5 seconds -- the plan's acceptance bar.
Exit 3 = rate limited (orchestrator should wait a minute and retry).
"""
import sys
import time
import os

import pytest


def _client(url, token=""):
    from battery_notifier.config import Config
    from battery_notifier.worker_client import WorkerClient
    cfg = Config()
    cfg.proxy_url = "direct"
    return WorkerClient(url, token, cfg)


def main():
    print(f"[boot] role={sys.argv[1]} pid={os.getpid()}", flush=True)
    role, marker = sys.argv[1], os.path.abspath(sys.argv[2])
    url = sys.argv[3] if len(sys.argv) > 3 else "https://battery-relay-staging.sthidontknow.workers.dev"
    tag = f"{role}-{os.name}-{int(time.time())}"

    wc = _client(url)
    token = wc.register(device_name=f"crossos-{tag}", platform=sys.platform)
    if not token:
        print("RESULT: register failed")
        sys.exit(2)

    if role == "send":
        # the listener publishes ITS token in the marker -- thief alerts must
        # land on the same account the victim polls (that's what pairing does)
        token = None
        deadline = time.time() + 45
        while time.time() < deadline and not token:
            try:
                cand = open(marker).read().strip()
                if len(cand) >= 32 and set(cand) <= set("0123456789abcdef"):
                    token = cand
                    break
            except FileNotFoundError:
                pass
            time.sleep(0.5)
        if not token:
            print("RESULT: no listener token appeared in marker")
            sys.exit(2)
        wc.token = token
        time.sleep(1.0)
        t0 = time.time()
        with open(marker, "w") as f:
            f.write(str(t0))
        ok = wc.send_alert(alert_type="THIEF_ALERT", battery_pct=42, is_charging=False)
        if not ok:
            err = wc.poll().get("error")
            print(f"RESULT: send failed ({err})")
            sys.exit(3 if err == "rate_limited" else 2)
        print(f"SENT at {t0:.3f}")
        sys.exit(0)

    # ---- listen ----
    # publish our token so the other OS can impersonate this account
    with open(marker, "w") as f:
        f.write(token)
    print(f"LISTENING token={token[:8]}... wrote marker", flush=True)
    deadline = time.time() + 40
    while time.time() < deadline:
        resp = wc.poll()
        if resp.get("error") == "rate_limited":
            print("RESULT: rate_limited")
            sys.exit(3)
        if resp.get("ok") and resp.get("alert_active"):
            try:
                t0 = float(open(marker).read().strip())
                elapsed = time.time() - t0
            except Exception as e:
                print(f"RESULT: marker unreadable: {e}")
                sys.exit(2)
            verdict = "PASS" if elapsed < 5 else "SLOW"
            print(f"RESULT: {verdict} elapsed={elapsed:.2f}s")
            wc.clear_alert()
            sys.exit(0 if elapsed < 5 else 1)
        time.sleep(0.4)
    print("RESULT: timeout -- no alert arrived in 25s")
    sys.exit(2)


if __name__ == "__main__":
    main()
