#!/usr/bin/env python3
"""Adversarial + edge-case tests against a REAL deployment (staging default).

Complements test_worker_live.py: this file is deliberately hostile -- XSS
payloads, bypass attempts, malformed auth, boundary values, re-link rotation.

Run: WORKER_URL=https://battery-relay-staging... ADMIN_KEY=... pytest -m live
"""
import json
import time
import os

import pytest

pytestmark = pytest.mark.live

WORKER_URL = os.environ.get(
    "WORKER_URL", "https://battery-relay-staging.sthidontknow.workers.dev"
)
ADMIN_KEY = os.environ.get("ADMIN_KEY", "")

_tag = str(int(time.time()))[-6:]
UA = {"User-Agent": "battery-music-adversarial/1.0"}


def _api(path, method="GET", token=None, body=None, timeout=15, extra_headers=None,
         raw_body=None):
    import urllib.request
    import urllib.error
    url = f"{WORKER_URL}{path}?_t={int(time.time() * 1000)}"
    headers = {"Content-Type": "application/json", **UA}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    data = raw_body if raw_body is not None else (
        json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}


def _register(name):
    s, b = _api("/api/register", "POST",
                body={"device_name": f"{name}-{_tag}", "platform": "test"})
    assert s == 200, (s, b)
    return b["token"]


def _admin_session():
    if not ADMIN_KEY:
        pytest.skip("ADMIN_KEY not set")
    s, b = _api("/admin/login", "POST", body={"admin_key": ADMIN_KEY})
    assert s == 200, b
    return b["session_key"]


# ---- transport / CORS ------------------------------------------------------

def test_options_preflight_has_cors():
    """OPTIONS must answer 2xx with the CORS headers workers promise."""
    import urllib.request
    req = urllib.request.Request(f"{WORKER_URL}/api/alert?_t={time.time()}",
                                 method="OPTIONS", headers=UA)
    with urllib.request.urlopen(req, timeout=10) as r:
        assert 200 <= r.status < 300
        assert r.headers.get("Access-Control-Allow-Origin") == "*"
        assert "Authorization" in (r.headers.get("Access-Control-Allow-Headers") or "")


def test_privacy_page_live():
    """/privacy exists and says the aggregate-only truth."""
    s, body = _api("/privacy")
    assert s == 200
    # body comes back parsed only if json; fetch raw instead
    import urllib.request
    html = urllib.request.urlopen(
        urllib.request.Request(f"{WORKER_URL}/privacy", headers=UA),
        timeout=10).read().decode()
    assert "aggregate" in html.lower()


# ---- auth boundaries -------------------------------------------------------

def test_auth_header_variants_all_rejected():
    for token in ("x" * 15,                       # below length floor
                  "",                              # empty
                  "a" * 48,                        # plausible but unknown
                  "../../etc/passwd",              # path-ish junk
                  "😀" * 12):                      # unicode
        s, _ = _api("/api/poll", "GET", token=token)
        assert s == 401, f"token {token[:12]!r} -> {s}"


def test_bearer_without_space_rejected():
    import urllib.request
    import urllib.error
    req = urllib.request.Request(f"{WORKER_URL}/api/poll?_t={time.time()}",
                                 headers={**UA, "Authorization": "Bearerabc123def4567890"})
    try:
        urllib.request.urlopen(req, timeout=10)
        assert False, "expected 401"
    except urllib.error.HTTPError as e:
        assert e.code == 401


# ---- input hostility -------------------------------------------------------

def test_xss_device_name_is_escaped_in_dashboard():
    """Register an XSS payload, then confirm the dashboard shows it escaped."""
    evil = '<script>alert(1)</script>'
    _register(evil)
    sk = _admin_session()
    import urllib.request
    req = urllib.request.Request(
        f"{WORKER_URL}/admin?_t={time.time()}",
        headers={**UA, "Authorization": f"Bearer {sk}"})
    html = urllib.request.urlopen(req, timeout=10).read().decode()
    assert "<script>alert(1)" not in html, "stored XSS executed in dashboard!"
    assert "&lt;script&gt;" in html


def test_alert_type_trims_and_normalizes():
    """' thief_Alert ' must normalize to THIEF_ALERT and keep its bypass."""
    token = _register("trim")
    s, b = _api("/api/alert", "POST", token=token,
                body={"alert_type": "  thief_Alert  ", "battery_pct": 50})
    assert s == 200 and b["alert_type"] == "THIEF_ALERT", b
    _api("/api/clear", "POST", token=token)


def test_alert_type_sliced_to_20_chars():
    token = _register("slice")
    long_type = "A" * 40
    s, b = _api("/api/alert", "POST", token=token,
                body={"alert_type": long_type})
    assert s == 200
    assert len(b["alert_type"]) == 20
    _api("/api/clear", "POST", token=token)


def test_extreme_battery_values_no_500():
    token = _register("extreme")
    for pct in (-999999, 999999, 0):
        s, _ = _api("/api/alert", "POST", token=token,
                    body={"alert_type": "BATTERY", "battery_pct": pct})
        assert s == 200, pct
    _api("/api/clear", "POST", token=token)


def test_one_mb_body_does_not_crash():
    """Garbage mega-payload: any sane answer beats a 500."""
    s, _ = _api("/api/register", "POST", raw_body=b'{"device_name":"' + b"A" * 1_000_000)
    assert s in (200, 400, 413), s


def test_non_json_body_graceful():
    s, _ = _api("/api/alert", "POST", token=_register("form"),
                raw_body=b"battery_pct=5", )
    assert s == 200  # body parse fails -> defaults kick in


# ---- pairing semantics -----------------------------------------------------

def test_pair_code_format_and_boundaries():
    _, reg = _register("pairfmt")
    s, b = _api("/api/pair/generate", "POST", token=reg["token"])
    assert s == 200 and len(b["code"]) == 6 and b["code"].isdigit()

    for bad in ("1234567", "12345", "abcdef", "12 456", ""):
        s, _ = _api("/api/pair/link", "POST", body={"code": bad})
        assert s == 400, bad


def test_unauthenticated_pair_generate_rejected():
    s, _ = _api("/api/pair/generate", "POST", body={})
    assert s == 401


def test_relink_rotates_linked_token_and_kicks_old_phone():
    """Documented security property: pairing a NEW phone de-authorizes the old one."""
    _, reg = _register("rotate")

    _, g1 = _api("/api/pair/generate", "POST", token=reg["token"])
    _, l1 = _api("/api/pair/link", "POST", body={"code": g1["code"]})
    phone_a = l1["token"]

    # phone A works...
    s, _ = _api("/api/poll", "GET", token=phone_a)
    assert s == 200

    # ...until phone B links
    _, g2 = _api("/api/pair/generate", "POST", token=reg["token"])
    _, l2 = _api("/api/pair/link", "POST", body={"code": g2["code"]})
    phone_b = l2["token"]
    assert phone_b != phone_a != reg["token"]

    s, _ = _api("/api/poll", "GET", token=phone_b)
    assert s == 200, "new phone must work"

    s, _ = _api("/api/poll", "GET", token=phone_a)
    assert s == 401, "old phone must be kicked after re-link"


def test_primary_token_survives_many_relings():
    _, reg = _register("survivor")
    laptop = reg["token"]
    for _ in range(3):
        _, g = _api("/api/pair/generate", "POST", token=laptop)
        _api("/api/pair/link", "POST", body={"code": g["code"]})
        s, _ = _api("/api/poll", "GET", token=laptop)
        assert s == 200, "laptop's own token must never be invalidated by linking"


# ---- rate-limit behaviour --------------------------------------------------

def test_thief_bypass_survives_mixed_case_flood():
    token = _register("flood")
    for i in range(31):
        _api("/api/alert", "POST", token=token,
             body={"alert_type": "BATTERY", "battery_pct": 10})
    # battery now limited; mixed-case thief must still punch through
    s, b = _api("/api/alert", "POST", token=token,
                body={"alert_type": "thief_alert", "battery_pct": 9})
    assert s == 200, "normalized THIEF_ALERT lost its bypass!"
    _api("/api/clear", "POST", token=token)


def test_daily_counters_move_after_activity():
    """Telemetry end-to-end: activity today must show up in admin daily[]"""
    sk = _admin_session()
    _, reg = _register("telemetryprobe")
    before = _api("/admin/stats", "GET", token=sk)[1]["daily"]
    today_before = next((d for d in before if d["day"] ==
                         time.strftime("%Y-%m-%d", time.gmtime())), None)
    n_before = today_before["registrations"] if today_before else 0

    _api("/api/alert", "POST", token=reg["token"],
         body={"alert_type": "BATTERY", "battery_pct": 77})

    after = _api("/admin/stats", "GET", token=sk)[1]["daily"]
    today_after = next(d for d in after if d["day"] ==
                       time.strftime("%Y-%m-%d", time.gmtime()))
    assert today_after["registrations"] >= max(n_before, 1)
    assert today_after["alerts"] >= 1
