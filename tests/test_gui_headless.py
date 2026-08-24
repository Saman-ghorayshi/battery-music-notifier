#!/usr/bin/env python3
"""Headless unit tests for the GUI services + bridge (no pywebview needed)."""
import threading
import time
from pathlib import Path

import pytest

from battery_notifier.config import Config
from battery_notifier.gui.bridge import Bridge, _MASK
from battery_notifier.gui.services import (
    RelayService,
    ServiceManager,
    StatusBus,
)


# ---------------------------------------------------------------- StatusBus

def test_statusbus_snapshot_is_isolated_copy():
    bus = StatusBus()
    snap = bus.snapshot()
    snap["relay"]["running"] = True  # mutate the copy
    assert bus.snapshot()["relay"]["running"] is False


def test_statusbus_update_section_and_root():
    bus = StatusBus()
    bus.update("thief", armed=True)
    bus.update(battery_pct=88)
    snap = bus.snapshot()
    assert snap["thief"]["armed"] is True
    assert snap["battery_pct"] == 88


# ------------------------------------------------------------- RelayService

class FakeWorker:
    def __init__(self, script):
        self.script = list(script)
        self.token = "t" * 48

    def poll(self):
        if len(self.script) > 1:
            return self.script.pop(0)
        return self.script[0]


class FakePlayer:
    def __init__(self):
        self.calls = []
    def play(self): self.calls.append("play")
    def stop(self): self.calls.append("stop")


def _relay_cfg(tmp_path):
    cfg = Config()
    cfg.worker_url = "https://worker.example"
    cfg.worker_token = "x" * 48
    return cfg


def test_relay_service_plays_and_stops_on_thief_alert(tmp_path):
    cfg = _relay_cfg(tmp_path)
    bus = StatusBus()
    player = FakePlayer()
    worker = FakeWorker([
        {"ok": True, "alert_active": 1, "alert_type": "THIEF_ALERT"},
        {"ok": True, "alert_active": 0, "alert_type": ""},
    ])
    svc = RelayService(cfg, bus, worker=worker, player=player)
    svc.start()
    deadline = time.time() + 8
    while time.time() < deadline and "play" not in player.calls:
        time.sleep(0.05)
    # force loop to see the cleared state on its next poll
    while time.time() < deadline and "stop" not in player.calls:
        time.sleep(0.05)
    svc.stop()
    svc.join(timeout=5)
    assert "play" in player.calls, f"alarm never played: {player.calls}"
    assert "stop" in player.calls, "alarm never stopped"
    snap = bus.snapshot()
    assert snap["relay"]["last_alert"].startswith("THIEF_ALERT")


def test_relay_service_no_worker_url_fails_fast():
    cfg = Config()  # worker_url defaults to DEFAULT_WORKER_URL; blank it
    cfg.worker_url = ""
    bus = StatusBus()
    svc = RelayService(cfg, bus, worker=FakeWorker([]), player=FakePlayer())
    svc.run()  # run inline (not as thread)
    assert bus.snapshot()["relay"]["running"] is False
    assert bus.snapshot()["relay"]["error"]


# ------------------------------------------------------------ ServiceManager

def test_manager_get_state_shape(tmp_path):
    mgr = ServiceManager(config_path=tmp_path / "missing.toml")
    try:
        state = mgr.get_state()
        for key in ("battery_pct", "charging", "thief", "relay", "serve", "heartbeat"):
            assert key in state
        assert isinstance(state["charging"], bool)
    finally:
        mgr.shutdown_all()


# ------------------------------------------------------------------- Bridge

@pytest.fixture()
def bridge_env(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        "# my precious comments\n"
        "[battery_notifier]\n"
        "music_files = []\n"
        "min_percentage = 20\n"
        "# keep me\n"
        "quiet_hours = [22, 8]\n",
        encoding="utf-8",
    )
    mgr = ServiceManager(config_path=cfg_path)
    return Bridge(mgr, config_path=cfg_path), mgr, cfg_path


def test_settings_round_trip_lossless(bridge_env):
    bridge, mgr, path = bridge_env
    r = bridge.save_settings({
        "min_percentage": 15,
        "max_percentage": 95.0,   # float must coerce to int
        "volume": 0.5,
        "poll_interval": 12,
        "annoying": True,
        "quiet_hours": [23, 7],
        "proxy_url": "direct",
        "worker_url": "https://my-worker.example",
        "music_files": ["C:/music/a.wav"],
        "email_smtp_port": 465,
    })
    assert r["ok"]

    reloaded = Config.load(path)
    assert reloaded.min_percentage == 15
    assert reloaded.max_percentage == 95
    assert isinstance(reloaded.max_percentage, int)
    assert abs(reloaded.volume - 0.5) < 1e-9
    assert reloaded.poll_interval == 12.0
    assert reloaded.annoying is True
    assert reloaded.quiet_hours == [23, 7]
    assert reloaded.proxy_url == "direct"
    assert reloaded.worker_url == "https://my-worker.example"
    assert reloaded.music_files == ["C:/music/a.wav"]
    assert reloaded.email_smtp_port == 465


def test_settings_preserve_comments(bridge_env):
    bridge, mgr, path = bridge_env
    bridge.save_settings({"volume": 0.3})
    text = path.read_text(encoding="utf-8")
    assert "# my precious comments" in text
    assert "# keep me" in text


def test_get_settings_masks_secrets_and_save_keeps_them(bridge_env):
    bridge, mgr, path = bridge_env
    bridge.save_settings({"telegram_token": "SECRET123", "admin_key": "ADMINKEY99"})
    got = bridge.get_settings()["settings"]
    assert got["telegram_token"] == _MASK
    assert got["admin_key"] == _MASK

    # UI echoes the mask back -> underlying secret survives
    bridge.save_settings({"telegram_token": _MASK})
    assert Config.load(path).telegram_token == "SECRET123"

    # explicit overwrite works too
    bridge.save_settings({"telegram_token": "NEW"})
    assert Config.load(path).telegram_token == "NEW"


def test_get_state_via_bridge(bridge_env):
    bridge, mgr, _ = bridge_env
    state = bridge.get_state()
    assert "battery_pct" in state and "thief" in state
