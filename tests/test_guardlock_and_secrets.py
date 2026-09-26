"""Tests for guardlock (single-instance / alarm-source locks), the relay
alert-episode logic, and DPAPI-encrypted secrets in config.toml."""
import os

import pytest

from battery_notifier import guardlock
from battery_notifier.config import (
    Config,
    encrypt_secret,
    decrypt_secret,
    _DPAPI_PREFIX,
)


# ---------------------------------------------------------------------------
# guardlock: single-instance + alarm-source locks
# ---------------------------------------------------------------------------

DEAD_PID = 99999999  # pid that certainly is not running


def test_acquire_writes_own_pid(tmp_path):
    lock = guardlock.acquire(tmp_path, guardlock.LOCK_RELAY)
    assert lock is not None
    assert lock.exists()
    assert lock.read_text().strip() == str(os.getpid())
    guardlock.release(lock)
    assert not lock.exists()


def test_acquire_blocks_while_live_holder_exists(tmp_path):
    first = guardlock.acquire(tmp_path, guardlock.LOCK_THIEF)
    assert first is not None
    # Our own pid is alive -> a second acquire must refuse.
    assert guardlock.acquire(tmp_path, guardlock.LOCK_THIEF) is None
    guardlock.release(first)


def test_stale_pid_lock_is_taken_over(tmp_path):
    lock = tmp_path / guardlock.LOCK_RELAY
    lock.write_text(str(DEAD_PID))
    second = guardlock.acquire(tmp_path, guardlock.LOCK_RELAY)
    assert second is not None  # dead pid -> takeover
    assert second.read_text().strip() == str(os.getpid())


def test_unparsable_lock_is_taken_over(tmp_path):
    lock = tmp_path / guardlock.LOCK_THIEF
    lock.write_text("not-a-pid\n")
    second = guardlock.acquire(tmp_path, guardlock.LOCK_THIEF)
    assert second is not None
    assert second.read_text().strip() == str(os.getpid())


def test_release_never_deletes_a_foreign_lock(tmp_path):
    lock = tmp_path / guardlock.LOCK_THIEF
    lock.write_text(str(DEAD_PID))
    guardlock.release(lock)
    assert lock.exists()  # not ours -> untouched
    # our own lock goes away
    mine = guardlock.acquire(tmp_path, guardlock.LOCK_THIEF)
    guardlock.release(mine)
    assert not mine.exists()


def test_release_is_safe_on_missing_path_and_none(tmp_path):
    guardlock.release(None)
    guardlock.release(tmp_path / "never-created.lock")  # must not raise
    guardlock.release(tmp_path / "subdir" / "missing.lock")  # must not raise


def test_is_locked_semantics(tmp_path):
    assert guardlock.is_locked(tmp_path, guardlock.LOCK_THIEF) is False
    lock = guardlock.acquire(tmp_path, guardlock.LOCK_THIEF)
    assert guardlock.is_locked(tmp_path, guardlock.LOCK_THIEF) is True  # our pid is alive
    guardlock.release(lock)
    assert guardlock.is_locked(tmp_path, guardlock.LOCK_THIEF) is False
    lock.write_text(str(DEAD_PID))
    assert guardlock.is_locked(tmp_path, guardlock.LOCK_THIEF) is False  # stale


def test_pid_alive_self():
    assert guardlock._pid_alive(os.getpid()) is True
    assert guardlock._pid_alive(DEAD_PID) is False
    assert guardlock._pid_alive(-1) is False
    assert guardlock._pid_alive("junk") is False


# ---------------------------------------------------------------------------
# Relay alert-episode logic (stuck-alert replay fix)
# ---------------------------------------------------------------------------

def _ep(ts, typ):
    return (ts, typ)


def test_episode_plays_once_per_alert_ts():
    from battery_notifier.cli import _relay_episode_should_play

    last = None
    # First sighting of the episode -> play.
    should_play, last = _relay_episode_should_play(last, 1, 1000, "THIEF_ALERT")
    assert should_play is True
    assert last == _ep(1000, "THIEF_ALERT")
    # Same alert_ts polled again (still active) -> never replay.
    should_play, last = _relay_episode_should_play(last, 1, 1000, "THIEF_ALERT")
    assert should_play is False
    # ...and again after the local sound was valve-stopped -> still no replay.
    should_play, last = _relay_episode_should_play(last, 1, 1000, "THIEF_ALERT")
    assert should_play is False


def test_episode_new_alert_ts_replays():
    from battery_notifier.cli import _relay_episode_should_play

    last = _ep(1000, "THIEF_ALERT")
    should_play, last = _relay_episode_should_play(last, 1, 2000, "THIEF_ALERT")
    assert should_play is True
    assert last == _ep(2000, "THIEF_ALERT")


def test_episode_type_change_replays():
    from battery_notifier.cli import _relay_episode_should_play

    last = _ep(1000, "BATTERY")
    should_play, last = _relay_episode_should_play(last, 1, 1000, "THIEF_ALERT")
    assert should_play is True


def test_episode_cleared_then_same_alert_does_not_replay():
    from battery_notifier.cli import _relay_episode_should_play

    last = _ep(1000, "THIEF_ALERT")
    # Alert cleared: no play, episode is remembered.
    should_play, last = _relay_episode_should_play(last, 0, 1000, "THIEF_ALERT")
    assert should_play is False
    assert last == _ep(1000, "THIEF_ALERT")
    # Same episode flapping active again -> still no replay.
    should_play, last = _relay_episode_should_play(last, 1, 1000, "THIEF_ALERT")
    assert should_play is False


def test_alert_annoying_by_type():
    from battery_notifier.cli import _alert_annoying

    assert _alert_annoying("THIEF_ALERT") is True   # loop the siren
    assert _alert_annoying("BATTERY") is False      # one song


# ---------------------------------------------------------------------------
# DPAPI secret encryption (Windows; skipped elsewhere)
# ---------------------------------------------------------------------------

def test_decrypt_plaintext_passthrough():
    assert decrypt_secret("") == ""
    assert decrypt_secret("plain_token") == "plain_token"


def test_encrypt_secret_empty_passthrough():
    assert encrypt_secret("") == ""


def test_decrypt_garbage_dpapi_value_is_safe():
    # Undecryptable values must never raise out of config load.
    assert decrypt_secret(_DPAPI_PREFIX + "!!!not-base64!!!") == ""


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_dpapi_roundtrip():
    stored = encrypt_secret("tok12345678abcdef")
    assert stored.startswith(_DPAPI_PREFIX)
    assert "tok12345678abcdef" not in stored  # ciphertext, not plaintext
    assert decrypt_secret(stored) == "tok12345678abcdef"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_encrypt_secret_idempotent_for_already_encrypted():
    once = encrypt_secret("secret-value-123456")
    assert encrypt_secret(once) == once


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_config_load_decrypts_dpapi_secrets(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        '[battery_notifier]\n'
        f'worker_token = "{encrypt_secret("tok12345678abcdef")}"\n'
        f'admin_key = "{encrypt_secret("admin-key-0123456789")}"\n'
    )
    cfg = Config.load(cfg_file)
    assert cfg.worker_token == "tok12345678abcdef"
    assert cfg.admin_key == "admin-key-0123456789"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI upgrade is Windows-only")
def test_config_load_upgrades_plaintext_secrets_once(tmp_path):
    cfg_file = tmp_path / "config.toml"
    original = (
        '[battery_notifier]\n'
        'worker_url = "https://my-worker.example.com"\n'
        'worker_token = "tok12345678abcdef"\n'
        'admin_key = "admin-key-0123456789"\n'
    )
    cfg_file.write_text(original)

    # In-memory values stay plaintext for this load...
    cfg = Config.load(cfg_file)
    assert cfg.worker_token == "tok12345678abcdef"
    assert cfg.admin_key == "admin-key-0123456789"

    # ...but the file was rewritten encrypted (best-effort upgrade).
    content = cfg_file.read_text()
    assert "worker_token = \"dpapi:" in content
    assert "admin_key = \"dpapi:" in content
    assert '"tok12345678abcdef"' not in content

    # Second load: idempotent (no plaintext left), values still decrypt.
    cfg2 = Config.load(cfg_file)
    assert cfg2.worker_token == "tok12345678abcdef"
    assert cfg2.admin_key == "admin-key-0123456789"


@pytest.mark.skipif(os.name != "nt", reason="DPAPI is Windows-only")
def test_save_worker_token_writes_encrypted(tmp_path, monkeypatch):
    import battery_notifier.cli as cli

    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('[battery_notifier]\nworker_token = "old_token_12345678"\n')
    monkeypatch.setattr(cli, "APP_DIR", tmp_path)

    cli._save_worker_token("tok12345678abcdef")
    content = cfg_file.read_text()
    assert "worker_token = \"dpapi:" in content
    assert '"tok12345678abcdef"' not in content
    assert '"old_token_12345678"' not in content

    # And the saved value loads back as plaintext.
    cfg = Config.load(cfg_file)
    assert cfg.worker_token == "tok12345678abcdef"


def test_save_worker_token_tolerates_missing_config(tmp_path, monkeypatch):
    import battery_notifier.cli as cli

    monkeypatch.setattr(cli, "APP_DIR", tmp_path)  # no config.toml in here
    cli._save_worker_token("tok12345678abcdef")  # must not raise
    assert not (tmp_path / "config.toml").exists()


def test_config_missing_file_still_works(tmp_path):
    cfg = Config.load(tmp_path / "does-not-exist.toml")
    assert cfg.worker_token == ""
    assert cfg.admin_key == ""
    assert cfg.poll_interval > 0


def test_harden_perms_is_safe_everywhere(tmp_path):
    from battery_notifier.config import harden_config_perms

    f = tmp_path / "config.toml"
    f.write_text("[battery_notifier]\n")
    harden_config_perms(f)  # no-op on Windows, chmod 0600 on POSIX
    assert f.exists()
