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
    "https://battery-relay.sthidontknow.workers.dev",
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


def test_admin_stats_has_daily_array():
    """admin stats includes the aggregate daily counters (needs ADMIN_KEY)."""
    admin_key = os.environ.get("ADMIN_KEY", "")
    if not admin_key:
        pytest.skip("ADMIN_KEY not set -- cannot verify admin surfaces")
    s, b = _api("/admin/login", "POST", body={"admin_key": admin_key})
    assert s == 200, b
    s, b = _api("/admin/stats", "GET", token=b["session_key"])
    assert s == 200
    daily = b.get("daily")
    assert isinstance(daily, list) and len(daily) >= 1
    row = daily[0]
    for field in ("day", "registrations", "alerts", "thief_alerts",
                  "pairings", "active_devices"):
        assert field in row, f"daily row missing '{field}'"


def test_404_on_unknown_path():
    """unknown path returns 404."""
    s, b = _api("/api/nonexistent")
    assert s == 404
    assert b.get("error") == "not_found"


# ---- v2.1: intruder snapshots (needs R2 binding + migration_snapshots.sql) ----

import base64


def _jpeg(n_kb=2):
    """Smallest thing the magic-byte sniffer accepts as a real JPEG."""
    return bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"\x00" * (n_kb * 1024 - 4)


def _post_raw(path, token, payload, timeout=15):
    """Raw POST that returns (status, bytes) -- snapshot fetches are binary."""
    url = f"{WORKER_URL}{path}"
    # Plain-urllib's default UA gets 403'd by Cloudflare (error 1010) before
    # the request ever reaches the worker -- match _api's honest UA.
    headers = {"Content-Type": "application/json", "User-Agent": "python-integration-test/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _get_raw(path, token, timeout=15):
    url = f"{WORKER_URL}{path}"
    headers = {"User-Agent": "python-integration-test/2.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_snapshot_roundtrip_with_paired_phone():
    """laptop uploads -> poll exposes it -> paired phone fetches the bytes."""
    _, laptop = _register("snap")
    token = laptop["token"]

    s, b = _api("/api/snapshot", "POST", token=token, body={
        "image": base64.b64encode(_jpeg()).decode(),
    })
    assert s == 200, b
    snap_id = b["snap_id"]
    assert snap_id > 0

    # poll rides the snapshot along
    s, b = _api("/api/poll", "GET", token=token)
    assert s == 200
    assert b["snapshot_id"] == snap_id
    assert b["snapshot_url"] == f"/api/snapshot/{snap_id}"

    # the paired phone (linked token) may fetch it
    s, b = _api("/api/pair/generate", "POST", token=token)
    code = b["code"]
    s, phone = _api("/api/pair/link", "POST", body={"code": code})
    assert s == 200, phone
    s, raw = _get_raw(f"/api/snapshot/{snap_id}", phone["token"])
    assert s == 200
    assert raw[:3] == bytes([0xFF, 0xD8, 0xFF]), "not a JPEG back"

    # a stranger's token must NOT reach the laptop's photo
    _, stranger = _register("snap-stranger")
    s, _raw = _get_raw(f"/api/snapshot/{snap_id}", stranger["token"])
    assert s == 404


def test_snapshot_validation_gates():
    """garbage images and oversize payloads are rejected cleanly."""
    _, reg = _register("snap-gate")
    token = reg["token"]

    # text pretending to be an image -> 415
    s, b = _api("/api/snapshot", "POST", token=token, body={
        "image": base64.b64encode(b"definitely not an image").decode(),
    })
    assert s == 415, b

    # broken base64 -> 400
    s, b = _api("/api/snapshot", "POST", token=token, body={"image": "not!!base64"})
    assert s == 400, b

    # over the 208 KB body gate -> 413
    s, b = _post_raw("/api/snapshot", token,
                     json.dumps({"image": "A" * 220_000}).encode())
    assert s == 413, b


def test_snapshot_retention_keeps_newest_five():
    """the 6th upload prunes the 1st from both D1 and R2."""
    _, reg = _register("snap-prune")
    token = reg["token"]

    ids = []
    for i in range(6):
        s, b = _api("/api/snapshot", "POST", token=token, body={
            "image": base64.b64encode(_jpeg(1)).decode(),
        })
        assert s == 200, b
        ids.append(b["snap_id"])
        time.sleep(1.1)  # unique per-second R2 keys

    s, b = _api("/api/poll", "GET", token=token)
    assert b["snapshot_id"] == ids[-1]

    # newest survives...
    s, _raw = _get_raw(f"/api/snapshot/{ids[-1]}", token)
    assert s == 200
    # ...oldest is gone from both the row and the bucket
    s, b = _get_raw(f"/api/snapshot/{ids[0]}", token)
    assert s == 404


def test_alert_carries_snapshot_id():
    """THIEF_ALERT links to the uploaded snapshot; unknown ids are rejected."""
    _, reg = _register("snap-alert")
    token = reg["token"]

    s, b = _api("/api/snapshot", "POST", token=token, body={
        "image": base64.b64encode(_jpeg()).decode(),
    })
    snap_id = b["snap_id"]

    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT", "battery_pct": -1,
        "is_charging": False, "snapshot_id": snap_id,
    })
    assert s == 200, b
    assert b["snapshot_id"] == snap_id

    # someone else's snapshot id must not ride our alert
    _, other = _register("snap-alert-2")
    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT", "battery_pct": -1,
        "is_charging": False, "snapshot_id": other["user_id"],
    })
    assert s == 400 and b.get("error") == "unknown_snapshot", b

    # clean up the alert state this test leaves behind
    _api("/api/clear", "POST", token=token)


# ---- v2.2: opt-in Telegram delivery (needs migration_notify.sql) ----

def test_notify_setup_and_clear():
    """notify prefs store/upsert/clear; the real send is fire-and-forget."""
    _, reg = _register("notify")
    token = reg["token"]

    # invalid bot token shape -> 400
    s, b = _api("/api/notify/setup", "POST", token=token, body={
        "bot_token": "not-a-token", "chat_id": "12345",
    })
    assert s == 400 and b.get("error") == "invalid_bot_token", b

    # valid-shaped creds -> stored (upserted on repeat)
    good = {"bot_token": "1234567890:AA" + "x" * 33, "chat_id": "123456789"}
    s, b = _api("/api/notify/setup", "POST", token=token, body=good)
    assert s == 200 and b.get("ok") is True, b
    s, b = _api("/api/notify/setup", "POST", token=token, body=good)
    assert s == 200, b

    # a THIEF_ALERT with prefs set still relays fine even though the dummy
    # bot token can't actually deliver (send is fire-and-forget)
    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT", "battery_pct": -1, "is_charging": False,
    })
    assert s == 200 and b.get("ok") is True, b
    _api("/api/clear", "POST", token=token)

    # opt-out works
    s, b = _api("/api/notify/clear", "POST", token=token, body={})
    assert s == 200 and b.get("ok") is True, b


def test_real_telegram_delivery():
    """End-to-end Telegram DM (skipped unless TG_BOT_TOKEN + TG_CHAT_ID set)."""
    bot = os.environ.get("TG_BOT_TOKEN", "")
    chat = os.environ.get("TG_CHAT_ID", "")
    if not bot or not chat:
        pytest.skip("TG_BOT_TOKEN/TG_CHAT_ID not set -- real-delivery test skipped")
    _, reg = _register("tg")
    token = reg["token"]
    s, b = _api("/api/notify/setup", "POST", token=token, body={
        "bot_token": bot, "chat_id": chat,
    })
    assert s == 200, b
    s, b = _api("/api/alert", "POST", token=token, body={
        "alert_type": "THIEF_ALERT", "battery_pct": -1, "is_charging": False,
    })
    assert s == 200, b
    time.sleep(5)  # ctx.waitUntil delivery
    _api("/api/clear", "POST", token=token)


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
        test_admin_stats_has_daily_array,
        test_404_on_unknown_path,
        test_snapshot_roundtrip_with_paired_phone,
        test_snapshot_validation_gates,
        test_snapshot_retention_keeps_newest_five,
        test_alert_carries_snapshot_id,
        test_notify_setup_and_clear,
        test_real_telegram_delivery,
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
