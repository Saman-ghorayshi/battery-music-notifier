#!/usr/bin/env python3
"""Proxy resolution matrix: config > env vars > port scan > direct opt-out.

detect_environment() is faked everywhere -- it spawns PowerShell on Windows
and we're testing decision logic, not adapter scanning.
"""
import pytest

from battery_notifier.config import Config
from battery_notifier import connection
from battery_notifier.connection import get_effective_proxy


@pytest.fixture(autouse=True)
def clean_proxy_env(monkeypatch):
    """Strip every proxy env var so tests start from a known-blank state."""
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy",
                 "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def no_scan(monkeypatch):
    """Replace the port-scan tier with a sentinel we can assert against."""
    class FakeEnv:
        auto_proxy = "socks5://127.0.0.1:12334"  # would come from a scan
    monkeypatch.setattr(connection, "detect_environment", lambda: FakeEnv())


# ---- precedence ----------------------------------------------------------

def test_config_wins_over_everything(no_scan, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://10.0.0.1:8118")
    cfg = Config()
    cfg.proxy_url = "socks5://127.0.0.1:10808"
    assert get_effective_proxy(cfg) == "socks5://127.0.0.1:10808"


def test_env_beats_port_scan(no_scan, monkeypatch):
    monkeypatch.setenv("https_proxy", "socks5://127.0.0.1:10808")
    assert get_effective_proxy(Config()) == "socks5://127.0.0.1:10808"
    # and the scan tier never ran
    assert get_effective_proxy(None) == "socks5://127.0.0.1:10808"


def test_port_scan_is_last_tier(no_scan):
    assert get_effective_proxy(Config()) == "socks5://127.0.0.1:12334"


def test_nothing_anywhere_means_direct(no_scan, monkeypatch):
    monkeypatch.setattr(
        connection, "detect_environment",
        lambda: type("E", (), {"auto_proxy": None})(),
    )
    assert get_effective_proxy(Config()) is None


# ---- env var details -----------------------------------------------------

def test_https_uppercase_preferred_over_http_lowercase(no_scan, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://a:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://b:2")
    assert get_effective_proxy(None) == "http://b:2"


def test_allproxy_used_when_no_http_vars(no_scan, monkeypatch):
    monkeypatch.setenv("ALL_PROXY", "socks5://hiddify.box:12334")
    assert get_effective_proxy(None) == "socks5://hiddify.box:12334"


def test_bare_port_env_gets_normalized(no_scan, monkeypatch):
    # v2rayN users paste just the port; sanitize turns it into socks5 url
    monkeypatch.setenv("HTTPS_PROXY", "10809")
    assert get_effective_proxy(None) == "http://127.0.0.1:10809"


def test_empty_env_value_ignored(no_scan, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "   ")
    assert get_effective_proxy(None) == "socks5://127.0.0.1:12334"


# ---- direct opt-out still supreme -----------------------------------------

def test_direct_optout_blocks_env_too(no_scan, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:10808")
    cfg = Config()
    cfg.proxy_url = "direct"
    assert get_effective_proxy(cfg) is None


def test_off_and_none_keywords_equal_direct():
    for word in ("off", "none", "Direct", "NONE"):
        cfg = Config()
        cfg.proxy_url = word
        assert get_effective_proxy(cfg) is None, word
