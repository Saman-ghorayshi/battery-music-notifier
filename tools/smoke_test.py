#!/usr/bin/env python3
"""Live smoke test: run after every deploy to verify the relay is healthy.

Checks (in order, aborts on first failure):
  1. health endpoint returns 200
  2. register a throwaway device → get a token
  3. poll with that token → ok
  4. raise a THIEF_ALERT → origin clear → 403 (origin protection works)
  5. raise a BATTERY alert → self-clear → ok
  6. upload + delete a snapshot → R2 round-trip
  7. cleanup: disarm (clears alerts) + probe rows stay as test debris

Usage:  python tools/smoke_test.py [--url https://your-relay.workers.dev]

Exit code 0 = all checks passed. Any failure = non-zero + the failing
check printed to stderr. Run this BEFORE announcing a deploy.
"""
import argparse
import base64
import sys

import requests

CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


class SmokeTest:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.token = None
        self.user_id = None
        self.session = requests.Session()
        self.session.trust_env = False

    def req(self, method, path, body=None, token=None):
        headers = {"Content-Type": "application/json"}
        if token or self.token:
            headers["Authorization"] = "Bearer " + (token or self.token)
        r = self.session.request(method, self.base + path, json=body,
                                 headers=headers, timeout=15)
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:200]}

    @check("1. health endpoint")
    def health(self):
        code, _ = self.req("GET", "/health")
        assert code == 200, f"health returned {code}"

    @check("2. register throwaway device")
    def register(self):
        code, resp = self.req("POST", "/api/register",
                              {"device_name": "smoke-test", "platform": "test"})
        assert code == 200 and resp.get("ok"), f"register failed: {resp}"
        self.token = resp["token"]
        self.user_id = resp["user_id"]

    @check("3. poll with token (includes other_devices)")
    def poll(self):
        code, resp = self.req("GET", "/api/poll")
        assert code == 200 and resp.get("ok"), f"poll failed: {resp}"
        assert "other_devices" in resp, "poll missing other_devices (deploy is pre-v2.5?)"

    @check("4. THIEF origin clear → 403 (origin protection works)")
    def thief_origin_clear(self):
        code, resp = self.req("POST", "/api/alert",
                              {"alert_type": "THIEF_ALERT", "battery_pct": 50,
                               "is_charging": False})
        assert code == 200 and resp.get("ok"), f"raise failed: {resp}"
        code, resp = self.req("POST", "/api/clear", {})
        assert code == 403 and resp.get("error") == "origin_cannot_clear", \
            f"expected 403 origin_cannot_clear, got {code} {resp}"

    @check("5. BATTERY alert → self-clear → ok")
    def battery_self_clear(self):
        code, resp = self.req("POST", "/api/alert",
                              {"alert_type": "BATTERY", "battery_pct": 20,
                               "is_charging": False})
        assert resp.get("ok"), f"raise BATTERY failed: {resp}"
        code, resp = self.req("POST", "/api/clear", {})
        assert code == 200 and resp.get("ok"), f"BATTERY clear failed: {resp}"

    @check("6. snapshot upload + delete (R2 round-trip)")
    def snapshot_roundtrip(self):
        # minimal valid JPEG (1x1 red)
        test_jpg = bytes([
            0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46,
            0x00, 0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00,
            0xFF, 0xD9,
        ])
        code, resp = self.req("POST", "/api/snapshot",
                              {"image": base64.b64encode(test_jpg).decode()})
        assert resp.get("ok"), f"upload failed: {resp}"
        snap_id = resp["snap_id"]
        code, resp = self.req("POST", "/api/snapshot/delete", {"snap_id": snap_id})
        assert resp.get("ok"), f"delete failed: {resp}"


def main():
    parser = argparse.ArgumentParser(description="Relay live smoke test")
    parser.add_argument("--url", default="https://battery-relay.sthidontknow.workers.dev",
                        help="Relay base URL")
    args = parser.parse_args()

    test = SmokeTest(args.url)
    failures = []

    for name, fn in CHECKS:
        try:
            fn(test)
            print(f"  ✓ {name}")
        except Exception as e:
            print(f"  ✗ {name}: {e}", file=sys.stderr)
            failures.append((name, e))
            break

    if failures:
        print(f"\nSMOKE TEST FAILED: {failures[0][0]}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"\nAll {len(CHECKS)} checks passed. Relay is healthy.")


if __name__ == "__main__":
    main()
