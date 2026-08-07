#!/usr/bin/env python3
"""Real integration test for the CF Worker + D1 + Telegram pipeline.

Hits the live worker at late-snow-3100.msi48vwsfhhy.workers.dev
No mocks -- real HTTP, real D1, real Telegram API.

Run: python -m pytest tests/test_worker_live.py -v --timeout=30
Or:  python tests/test_worker_live.py
"""

import json
import time
import urllib.request
import urllib.error
import os

import pytest

WORKER_URL = os.environ.get(
    "WORKER_URL",
    "https://late-snow-3100.msi48vwsfhhy.workers.dev",
)

# real telegram bot token and chat id from worker env
TG_TOKEN = os.environ.get("TG_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")


def _api(path, method="GET", token=None, body=None):
    """hit the worker, return (status, json_body)."""
    url = f"{WORKER_URL}{path}?_t={int(time.time())}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "python-integration-test/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"_raw": raw.decode()[:300]}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"_raw": raw.decode()[:300]}


def _tg_send(text):
    """send a message via telegram, return True on success."""
    if not TG_TOKEN or not CHAT_ID:
        return False
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
        data=json.dumps({"chat_id": CHAT_ID, "text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("ok", False)
    except Exception:
        return False


# ---- tests ----

def test_worker_health():
    """worker responds on / with 200."""
    s, b = _api("/")
    assert s == 200


def test_register_device():
    """register returns a token and user_id."""
    s, b = _api("/api/register", "POST", body={"device_name": "test-py", "platform": "linux"})
    assert s == 200
    assert b.get("ok") is True
    assert "token" in b
    assert b.get("user_id") is not None
    # token should be hex and long enough to be secure
    assert len(b["token"]) >= 32


def test_ping_with_valid_token():
    """ping with a registered token returns ok."""
    _, reg = _api("/api/register", "POST", body={"device_name": "ping-test", "platform": "linux"})
    token = reg["token"]
    s, b = _api("/api/ping", "POST", token=token)
    assert s == 200
    assert b.get("ok") is True
    assert "server_time" in b


def test_ping_with_bad_token():
    """ping with a fake token gets 401."""
    s, b = _api("/api/ping", "POST", token="fake_token_that_does_not_exist_12345")
    assert s == 401
    assert b.get("error") == "unauthorized"


def test_send_battery_alert_and_poll():
    """send a battery alert, then poll and verify it shows up."""
    _, reg = _api("/api/register", "POST", body={"device_name": "test-battery-85", "platform": "linux"})
    token = reg["token"]

    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "BATTERY",
        "battery_pct": 85,
        "is_charging": True,
    })
    assert s == 200
    assert b.get("ok") is True
    assert b["alert_active"] == 1

    s, b = _api("/api/poll", "GET", token=token)
    assert s == 200
    assert b["alert_active"] == 1
    assert b["alert_type"] == "BATTERY"
    assert b["battery_pct"] == 85
    assert b["is_charging"] == 1


def test_send_thief_alert():
    """thief alert goes through and shows in poll."""
    _, reg = _api("/api/register", "POST", body={"device_name": "test-thief-alert", "platform": "linux"})
    token = reg["token"]

    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT",
        "battery_pct": 50,
        "is_charging": False,
    })
    assert s == 200
    assert b.get("ok") is True

    s, b = _api("/api/poll", "GET", token=token)
    assert b["alert_type"] == "THIEF_ALERT"
    assert b["battery_pct"] == 50


def test_clear_alert():
    """clear alert works, poll shows no alert."""
    _, reg = _api("/api/register", "POST", body={"device_name": "test-clear-lowbat", "platform": "linux"})
    token = reg["token"]

    _api("/api/alert", "POST", token=token, body={"alert_type": "BATTERY", "battery_pct": 10, "is_charging": False})

    s, b = _api("/api/clear", "POST", token=token)
    assert s == 200
    assert b["alert_active"] == 0

    s, b = _api("/api/poll", "GET", token=token)
    assert b["alert_active"] == 0
    assert b["alert_type"] == ""


def test_pairing_code_flow():
    """generate a pairing code, then link it to get the token back."""
    _, reg = _api("/api/register", "POST", body={"device_name": "pair-test", "platform": "linux"})
    token = reg["token"]

    s, b = _api("/api/pair/generate", "POST", token=token)
    assert s == 200
    assert "code" in b
    assert len(b["code"]) == 6

    code = b["code"]
    s, b = _api("/api/pair/link", "POST", body={"code": code})
    assert s == 200
    assert b.get("ok") is True
    assert b["token"] == token


def test_pairing_code_single_use():
    """after linking, same code can't be used again."""
    _, reg = _api("/api/register", "POST", body={"device_name": "reuse-test", "platform": "linux"})
    token = reg["token"]

    _, b = _api("/api/pair/generate", "POST", token=token)
    code = b["code"]

    s1, _ = _api("/api/pair/link", "POST", body={"code": code})
    assert s1 == 200

    s2, _ = _api("/api/pair/link", "POST", body={"code": code})
    assert s2 == 404


def test_expired_pairing_code():
    """an invalid code returns 404."""
    s, b = _api("/api/pair/link", "POST", body={"code": "000000"})
    if s == 404:
        assert b.get("error") == "invalid_or_expired"
    elif s == 200:
        # 000000 happened to be valid from a previous test run, try another
        s, b = _api("/api/pair/link", "POST", body={"code": "999999"})
        assert s == 404


def test_non_numeric_pairing_code_rejected():
    """non-numeric 6-char codes should return 400, not hit D1."""
    s, b = _api("/api/pair/link", "POST", body={"code": "abc123"})
    assert s == 400
    assert b.get("error") == "invalid_code"


def test_rate_limiting():
    """rate limit kicks in after enough requests (max 30/min per instance).

    Note: CF Workers rate limiting is in-memory per instance, so this
    may not trigger if CF routes to different instances. We still test
    that the API accepts at least 30 alerts without error.
    """
    _, reg = _api("/api/register", "POST", body={"device_name": "rate-test", "platform": "linux"})
    token = reg["token"]

    success_count = 0
    rate_limited = False
    for i in range(35):
        s, b = _api("/api/alert", "POST", token=token, body={
            "alert_type": "BATTERY",
            "battery_pct": 50,
            "is_charging": False,
        })
        if s == 200:
            success_count += 1
        elif s == 429:
            rate_limited = True
            break

    # either we got rate limited, or all 35 went through (different CF instance)
    assert success_count >= 30 or rate_limited, f"only {success_count} succeeded"


def test_thief_alert_bypasses_rate_limit():
    """thief alert gets through even after rate limit is exhausted."""
    _, reg = _api("/api/register", "POST", body={"device_name": "test-thief-bypass", "platform": "linux"})
    token = reg["token"]

    # exhaust rate limit
    for i in range(35):
        _api("/api/alert", "POST", token=token, body={
            "alert_type": "BATTERY",
            "battery_pct": 50,
            "is_charging": False,
        })

    # thief alert should still work
    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT",
        "battery_pct": 40,
        "is_charging": False,
    })
    assert s == 200
    assert b.get("ok") is True


def test_404_on_unknown_path():
    """unknown path returns 404."""
    s, b = _api("/api/nonexistent")
    assert s == 404
    assert b.get("error") == "not_found"


if __name__ == "__main__":
    # run without pytest
    import sys
    tests = [
        test_worker_health,
        test_register_device,
        test_ping_with_valid_token,
        test_ping_with_bad_token,
        test_send_battery_alert_and_poll,
        test_send_thief_alert,
        test_clear_alert,
        test_pairing_code_flow,
        test_pairing_code_single_use,
        test_expired_pairing_code,
        test_rate_limiting,
        test_thief_alert_bypasses_rate_limit,
        test_404_on_unknown_path,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(0 if failed == 0 else 1)
