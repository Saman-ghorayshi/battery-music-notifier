#!/usr/bin/env python3
"""Real integration test for the CF Worker / D1 pipeline (v2.0 semantics).

Hits the deployed worker -- real HTTP, real D1. No mocks.

v2.0 notes:
  - no server-side telegram push anymore (clients deliver their own)
  - pair/link mints a FRESH linked_token; the original device token stays valid
  - registrations are throttled server-side (10/min/ip), so this suite shares
    tokens where possible and backs off once if the cap bites

Run: pytest -m live
Or:  python tests/test_worker_live.py
"""

import json
import time
import urllib.request
import urllib.error
import os

import pytest

# Every test in this file hits the REAL worker/D1. Never run in CI
# or plain `pytest`; execute explicitly with:  pytest -m live
pytestmark = pytest.mark.live

WORKER_URL = os.environ.get(
    "WORKER_URL",
    "https://late-snow-3100.msi48vwsfhhy.workers.dev",
)


def _api(path, method="GET", token=None, body=None, timeout=10):
    """hit the worker, return (status, json_body)."""
    url = f"{WORKER_URL}{path}?_t={int(time.time() * 1000)}"
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "python-integration-test/2.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


_run_tag = str(int(time.time()))[-5:]


def _register(label):
    """register a device; back off once if the per-ip register cap bites."""
    s, b = _api("/api/register", "POST", body={
        "device_name": f"{label}-{_run_tag}", "platform": "linux",
    })
    if s == 429:
        # register cap is 10/min/ip -- wait out the window and retry once
        time.sleep(62)
        s, b = _api("/api/register", "POST", body={
            "device_name": f"{label}-{_run_tag}", "platform": "linux",
        })
    return s, b


# ---- tests ----

def test_worker_health():
    """worker responds on / with 200."""
    s, b = _api("/")
    assert s == 200


def test_register_device():
    """register returns a hex token >= 32 chars plus a user id."""
    s, b = _api("/api/register", "POST", body={
        "device_name": f"probe-{_run_tag}", "platform": "linux",
    })
    assert s == 200
    assert b.get("ok") is True
    assert len(b["token"]) >= 32
    int(b["token"], 16)  # must be hex
    assert b.get("user_id") is not None


def test_ping_with_valid_token():
    """ping with a registered token returns ok."""
    _, reg = _register("ping")
    s, b = _api("/api/ping", "POST", token=reg["token"])
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
    _, reg = _register("battery")
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


def test_thief_alert_is_fast():
    """thief alerts go through immediately -- no server-side push anymore.

    The v1 worker blocked up to ~11s sending telegram messages; v2.0 removed
    that. The relay should answer well under a second of processing.
    """
    _, reg = _register("thief")
    token = reg["token"]

    start = time.time()
    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT",
        "battery_pct": 50,
        "is_charging": False,
    }, timeout=15)
    elapsed = time.time() - start

    assert s == 200
    assert b.get("ok") is True
    assert elapsed < 8, f"thief alert took {elapsed:.1f}s -- push code back?"

    s, b = _api("/api/poll", "GET", token=token)
    assert b["alert_type"] == "THIEF_ALERT"
    assert b["battery_pct"] == 50
    _api("/api/clear", "POST", token=token)


def test_clear_alert():
    """clear alert works, poll shows no alert."""
    _, reg = _register("clear")
    token = reg["token"]

    _api("/api/alert", "POST", token=token, body={"alert_type": "BATTERY", "battery_pct": 10, "is_charging": False})

    s, b = _api("/api/clear", "POST", token=token)
    assert s == 200
    assert b["alert_active"] == 0

    s, b = _api("/api/poll", "GET", token=token)
    assert b["alert_active"] == 0
    assert b["alert_type"] == ""


def test_pairing_mints_linked_token():
    """pair/link returns a NEW token; both old and new authenticate."""
    _, reg = _register("pair")
    laptop = reg["token"]

    s, b = _api("/api/pair/generate", "POST", token=laptop)
    assert s == 200
    assert len(b["code"]) == 6

    s, b = _api("/api/pair/link", "POST", body={"code": b["code"]})
    assert s == 200
    phone = b["token"]
    assert phone != laptop, "link must mint a fresh token, not echo the primary"
    int(phone, 16)

    # phone can act as the same account...
    s, b = _api("/api/alert", "POST", token=phone, body={
        "alert_type": "BATTERY", "battery_pct": 33, "is_charging": False,
    })
    assert s == 200
    # ...and so can the laptop -- linking must not have invalidated it
    s, b = _api("/api/poll", "GET", token=laptop)
    assert s == 200
    assert b["battery_pct"] == 33
    _api("/api/clear", "POST", token=laptop)


def test_pairing_code_single_use():
    """after linking, same code can't be used again."""
    _, reg = _register("reuse")
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
        # astronomically unlucky guess hit a live code; try another
        s, b = _api("/api/pair/link", "POST", body={"code": "999999"})
        assert s == 404


def test_non_numeric_pairing_code_rejected():
    """non-numeric 6-char codes should return 400, not hit D1."""
    s, b = _api("/api/pair/link", "POST", body={"code": "abc123"})
    assert s == 400
    assert b.get("error") == "invalid_code"


def test_rate_limiting():
    """user alert limit is 30/min; THIEF_ALERT exempt (in-memory per instance).

    CF may route requests to a fresh isolate mid-run which resets counters --
    accept either outcome, just prove the endpoint holds up under load.
    """
    _, reg = _register("rate")
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

    assert success_count >= 30 or rate_limited, f"only {success_count} succeeded"


def test_thief_alert_bypasses_rate_limit():
    """thief alert gets through even after the user limit is exhausted."""
    _, reg = _register("bypass")
    token = reg["token"]

    for i in range(35):
        _api("/api/alert", "POST", token=token, body={
            "alert_type": "BATTERY",
            "battery_pct": 50,
            "is_charging": False,
        })

    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT",
        "battery_pct": 40,
        "is_charging": False,
    }, timeout=15)
    assert s == 200
    assert b.get("ok") is True


def test_404_on_unknown_path():
    """unknown path returns 404."""
    s, b = _api("/api/nonexistent")
    assert s == 404
    assert b.get("error") == "not_found"


if __name__ == "__main__":
    import sys
    tests = [
        test_worker_health,
        test_register_device,
        test_ping_with_valid_token,
        test_ping_with_bad_token,
        test_send_battery_alert_and_poll,
        test_thief_alert_is_fast,
        test_clear_alert,
        test_pairing_mints_linked_token,
        test_pairing_code_single_use,
        test_expired_pairing_code,
        test_non_numeric_pairing_code_rejected,
        test_rate_limiting,
        test_thief_alert_bypasses_rate_limit,
        test_404_on_unknown_path,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed}/{passed + failed} passed")
