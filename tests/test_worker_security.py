#!/usr/bin/env python3
"""Live security verification vs a real deployment (staging default).

Covers the P0 hardening: pair brute shield, body-size gate, CORS absence,
security headers. Never touches MAINTENANCE_MODE (that's an ops lever).

Run: WORKER_URL=<url> ADMIN_KEY=<key> pytest -m live
"""
import json
import json
import time
import os

import pytest

pytestmark = pytest.mark.live

WORKER_URL = os.environ.get(
    "WORKER_URL", "https://battery-relay-staging.sthidontknow.workers.dev"
)
UA = {"User-Agent": "battery-music-security/1.0"}
_tag = str(int(time.time()))[-6:]


def _raw(method, path, headers=None, data=None):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(
        f"{WORKER_URL}{path}?_t={int(time.time() * 1000)}",
        headers={"User-Agent": UA["User-Agent"], **(headers or {})},
        data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_security_headers_present():
    s, h, _ = _raw("GET", "/health")
    assert s == 200
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert h.get("Referrer-Policy") == "no-referrer"


def test_no_wildcard_cors():
    s, h, _ = _raw("OPTIONS", "/api/alert")
    assert s == 204
    assert "Access-Control-Allow-Origin" not in h, "wildcard CORS is back!"


def test_oversize_body_rejected():
    body = b'{"device_name":"' + b"A" * 20000 + b'"}'
    s, _, _ = _raw("POST", "/api/register",
                   headers={"Content-Type": "application/json"}, data=body)
    assert s in (400, 413), f"oversize body -> {s}"


def test_pair_link_brute_shield():
    """14 wrong codes from one IP must trip the 10/min pair-link cap."""
    saw429 = False
    for i in range(14):
        code = str(300000 + i * 13)  # wrong codes, valid format
        s, _, _ = _raw("POST", "/api/pair/link",
                       headers={"Content-Type": "application/json"},
                       data=json.dumps({"code": code}).encode())
        if s == 429:
            saw429 = True
        else:
            assert s in (400, 404), (i, s)
        if saw429:
            break
    assert saw429, "pair brute force was not capped"



