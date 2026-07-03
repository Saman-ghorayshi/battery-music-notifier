from __future__ import annotations
import argparse
import sys
import logging
from pathlib import Path
from .config import Config, APP_DIR, DEFAULT_WORKER_URL, DEFAULT_ALARM_FILE
from .logs import setup_logging
from .monitor import Monitor
from .connection import detect_environment

log = logging.getLogger(__name__)


def _save_worker_token(token: str) -> None:
    """Save the worker token into the config file for future sessions."""
    try:
        import tomllib
        import re
        cfg_path = APP_DIR / "config.toml"
        if not cfg_path.exists():
            return
        content = cfg_path.read_text()
        if 'worker_token' in content:
            # Replace existing token (space-tolerant regex handles "worker_token=value" too)
            content = re.sub(
                r'worker_token\s*=\s*"[^"]*"',
                f'worker_token = "{token}"',
                content,
            )
        else:
            content += f'\nworker_token = "{token}"\n'
        cfg_path.write_text(content)
        log.info("Worker token saved to config.")
    except Exception as e:
        log.warning("Failed to save worker token: %s", e)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="battery-music",
        description="Play music when battery reaches target.",
    )
    p.add_argument("-V", "--version", action="version", version="%(prog)s 1.2.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    # start: one-command auto-detect (the smart entry point)
    start = sub.add_parser(
        "start",
        help="Auto-detect role and start. Run this on both laptop and phone.",
    )
    start.add_argument("--host", default="auto", help="Override host (default: auto-discover)")
    start.add_argument("--port", type=int, default=8000, help="Port to use")
    start.add_argument("-v", "--verbose", action="store_true")
    start.add_argument("--config", type=Path)

    # run: standalone local monitoring (original behavior)
    run = sub.add_parser("run", help="Start local monitoring (single device).")
    run.add_argument("-m", "--music", action="append", default=[])
    run.add_argument("--min", type=int)
    run.add_argument("--max", type=int)
    run.add_argument("--volume", type=float)
    run.add_argument("--poll", type=float)
    run.add_argument("--annoying", action="store_true")
    run.add_argument("-v", "--verbose", action="store_true")
    run.add_argument("--config", type=Path)

    sub.add_parser("battery", help="Print current battery info and exit.")
    sub.add_parser("doctor", help="Scan local machine configurations and system hooks for conflicts.")

    init = sub.add_parser("init", help="Run setup wizard and write config file.")
    init.add_argument("--force", action="store_true")

    # serve: server mode (laptop side)
    serve = sub.add_parser("serve", help="Start the notification server (run on laptop).")
    serve.add_argument(
        "--host", default="auto",
        help="Host to bind. 'auto' tries 0.0.0.0 then 127.0.0.1 (default: auto)",
    )
    serve.add_argument("--port", type=int, default=8000, help="Port to listen on.")
    serve.add_argument("-v", "--verbose", action="store_true")
    serve.add_argument("--config", type=Path)

    # client: client mode (phone side)
    client = sub.add_parser("client", help="Start the remote battery monitor (run on phone).")
    client.add_argument(
        "--host", default="auto",
        help="Laptop address. 'auto' discovers via USB/UDP/subnet scan (default: auto)",
    )
    client.add_argument("--port", type=int, default=8000, help="Laptop socket port.")
    client.add_argument("-v", "--verbose", action="store_true")
    client.add_argument("--config", type=Path)

    # arm: thief catcher mode
    arm = sub.add_parser("arm", help="Arm thief catcher: alarm if charger unplugged.")
    arm.add_argument("--mode", choices=["local", "relay", "both"], default="both",
                     help="Alert mode: local (play here), relay (send to worker), both (default)")
    arm.add_argument("--force", action="store_true", help="Arm even if not currently charging")
    arm.add_argument("--port", type=int, default=8000, help="Local socket port for fallback")
    arm.add_argument("-v", "--verbose", action="store_true")
    arm.add_argument("--config", type=Path)

    # disarm: not needed as separate command (Ctrl+C disarms), but add for completeness
    # relay: run as relay server (laptop polls worker, plays alarm on THIEF_ALERT)
    relay = sub.add_parser("relay", help="Run relay listener: polls worker and plays alarm on alert.")
    relay.add_argument("--port", type=int, default=8000, help="Local socket port for fallback")
    relay.add_argument("-v", "--verbose", action="store_true")
    relay.add_argument("--config", type=Path)

    # admin: admin actions
    admin = sub.add_parser("admin", help="Admin dashboard and controls.")
    admin.add_argument("action", choices=["stats", "ban", "unban", "broadcast", "clear", "login"],
                       help="Admin action to perform")
    admin.add_argument("--user-id", type=int, help="User ID for ban/unban")
    admin.add_argument("--alert-type", default="TEST", help="Alert type for broadcast")
    admin.add_argument("--config", type=Path)

    return p


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    # ── init wizard ──
    if args.cmd == "init":
        target = APP_DIR / "config.toml"
        if target.exists() and not args.force:
            print(f"Config already exists at {target} (use --force to overwrite)")
            return 1

        print(" Welcome to the Battery Music Notifier setup!")

        # Numeric input helpers with validation (prevents TOML injection / crash)
        def ask_int(prompt, default):
            val = input(prompt).strip() or str(default)
            try:
                return int(val)
            except ValueError:
                print(f"  Invalid number, using default {default}.")
                return default

        def ask_float(prompt, default):
            val = input(prompt).strip() or str(default)
            try:
                return float(val)
            except ValueError:
                print(f"  Invalid number, using default {default}.")
                return default

        print("\n[Opening file dialog to select your music file...]")
        music_path = ""
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            music_path = filedialog.askopenfilename(
                title="Select Battery Notification Music",
                filetypes=[("Audio Files", "*.wav *.mp3 *.flac"), ("All Files", "*.*")]
            )
            root.destroy()
        except ImportError:
            pass

        if not music_path:
            print(" No file selected or graphical interface unavailable. Fallback: manual entry.")
            music_path = input("Enter path to your music file: ").strip()
        else:
            print(f" Selected: {music_path}")

        min_pct = ask_int("Enter minimum battery percentage to trigger [20]: ", 20)
        max_pct = ask_int("Enter maximum battery percentage [100]: ", 100)
        if min_pct >= max_pct:
            print("  [WARN] min must be less than max. Resetting to defaults (20/100).")
            min_pct, max_pct = 20, 100
        volume = ask_float("Enter volume 0.0 to 1.0 [0.8]: ", 0.8)
        if not (0.0 <= volume <= 1.0):
            print("  [WARN] volume must be 0.0-1.0. Resetting to 0.8.")
            volume = 0.8
        poll = ask_float("Enter poll interval in seconds [3.0]: ", 3.0)
        if poll <= 0:
            print("  [WARN] poll interval must be positive. Resetting to 3.0.")
            poll = 3.0
        annoying_ans = input("Loop music annoyingly until unplugged? (y/N): ").strip().lower()
        annoying = "true" if annoying_ans in ("y", "yes") else "false"

        print("\n [Quiet Hours (Do Not Disturb)]")
        quiet_start = ask_int("Enter quiet hours start (24h format, e.g., 22) [22]: ", 22)
        quiet_end = ask_int("Enter quiet hours end (24h format, e.g., 8) [8]: ", 8)
        if not (0 <= quiet_start <= 23) or not (0 <= quiet_end <= 23):
            print("  [WARN] quiet hours must be 0-23. Resetting to 22/8.")
            quiet_start, quiet_end = 22, 8

        print("\n [Network Proxy Configuration Settings]")
        use_proxy = input("Do you need a proxy to bypass network blocks/Telegram restrictions? (y/N): ").strip().lower()
        proxy_url = ""
        if use_proxy in ("y", "yes"):
            print("\nSelect your proxy core protocol:")
            print("  [1] SOCKS5 (Recommended for v2rayN: 10808, Hiddify: 12334, Nekoray: 2080)")
            print("  [2] HTTP   (Recommended for Clash: 7890, v2rayN HTTP: 10809)")
            ptype = input("Choose protocol option [1]: ").strip() or "1"
            host = input("Enter proxy connection host IP [127.0.0.1]: ").strip() or "127.0.0.1"
            port = input("Enter proxy connection port number (e.g., 10808): ").strip()
            while not port.isdigit():
                print(" Invalid entry. Port must be numerical.")
                port = input("Enter proxy connection port number: ").strip()
            proto = "http" if ptype == "2" else "socks5"
            proxy_url = f"{proto}://{host}:{port}"

        print("\n [Telegram Notification Setup]")
        print("  Get token from @BotFather, chat ID from @userinfobot")
        telegram_token = ""
        telegram_chat_id = ""
        tg_ans = input("Do you want Telegram notifications? (y/N): ").strip().lower()
        if tg_ans in ("y", "yes"):
            telegram_token = input("  Enter your Telegram Bot Token: ").strip()
            telegram_chat_id = input("  Enter your Telegram Chat ID: ").strip()

        print("\n [Email Notification Setup]")
        email_smtp_server = "smtp.gmail.com"
        email_smtp_port = 587
        email_sender = ""
        email_password = ""
        email_receiver = ""
        em_ans = input("Do you want Email notifications? (y/N): ").strip().lower()
        if em_ans in ("y", "yes"):
            email_smtp_server = input("  Enter SMTP server [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
            port_in = input("  Enter SMTP port (587 for TLS, 465 for SSL) [587]: ").strip() or "587"
            email_smtp_port = int(port_in) if port_in.isdigit() else 587
            email_sender = input("  Enter sender email address: ").strip()
            email_password = input("  Enter email password (or app password): ").strip()
            email_receiver = input("  Enter receiver email address: ").strip()

        autostart_ans = input("\nDo you want to automatically start this app on boot? (y/N): ").strip().lower()
        enable_auto = autostart_ans in ("y", "yes")

        # Worker relay setup
        print("\n [Worker Relay Setup]")
        print("  A worker relay lets devices talk over the internet (no local network needed).")
        print(f"  Default hosted worker: {DEFAULT_WORKER_URL}")
        print("  (Already configured. Just press Enter to use it.)")
        print("  Paranoid? Self-host: see worker/README.md for instructions.")
        worker_url = DEFAULT_WORKER_URL
        worker_token = ""
        admin_key = ""
        w_ans = input("Use default hosted worker? (Y/n): ").strip().lower()
        if w_ans in ("n", "no"):
            worker_url = input("  Enter your self-hosted worker URL: ").strip()
            wt_ans = input("  Do you already have a token? (y/N): ").strip().lower()
            if wt_ans in ("y", "yes"):
                worker_token = input("  Enter your worker token: ").strip()
            ak_ans = input("  Enter admin key (or press Enter to skip): ").strip()
            if ak_ans:
                admin_key = ak_ans
        else:
            ak_ans = input("  Enter admin key (optional, for admin commands): ").strip()
            if ak_ans:
                admin_key = ak_ans

        # Thief catcher alarm sound
        print("\n [Thief Catcher Alarm Sound]")
        print(f"  Default alarm bundled at: assets/default_alarm.wav")
        print("  (A loud siren beep. You can set a custom one below.)")
        alarm_path = DEFAULT_ALARM_FILE
        al_ans = input("Use custom alarm sound? (y/N): ").strip().lower()
        if al_ans in ("y", "yes"):
            alarm_path = input("  Enter path to alarm sound file: ").strip()

        # Local socket shared secret (optional security feature)
        print("\n [Local Socket Security]")
        print("  Optional: set a shared secret to prevent LAN attackers from")
        print("  sending STOP to silence the thief-catcher alarm.")
        socket_secret = ""
        sec_ans = input("Set a socket secret? (y/N): ").strip().lower()
        if sec_ans in ("y", "yes"):
            import secrets as _secrets
            socket_secret = _secrets.token_hex(8)
            print(f"  Generated secret: {socket_secret}")
            print("  (Saved to config. Both devices must use the same secret.)")

        APP_DIR.mkdir(parents=True, exist_ok=True)

        # For TOML: use double-quoted strings with escaping for all string values.
        # Paths need backslash escaping (Windows), and all strings need quote escaping.
        # Numeric values (int/float) are written bare.
        def esc(s): return s.replace("\\", "\\\\").replace('"', '\\"')

        target.write_text(
            f'''[battery_notifier]
music_files = ["{esc(music_path)}"]
min_percentage = {min_pct}
max_percentage = {max_pct}
volume = {volume}
poll_interval = {float(poll)}
annoying = {annoying}
quiet_hours = [{int(quiet_start)}, {int(quiet_end)}]
proxy_url = "{esc(proxy_url)}"

# Telegram Integration
telegram_token = "{esc(telegram_token)}"
telegram_chat_id = "{esc(telegram_chat_id)}"

# Email Integration
email_smtp_server = "{esc(email_smtp_server)}"
email_smtp_port = {email_smtp_port}
email_sender = "{esc(email_sender)}"
email_password = "{esc(email_password)}"
email_receiver = "{esc(email_receiver)}"

# Worker Relay
worker_url = "{esc(worker_url)}"
worker_token = "{esc(worker_token)}"
admin_key = "{esc(admin_key)}"

# Thief Catcher Alarm
alarm_files = ["{esc(alarm_path)}"]

# Local Socket Security (optional shared secret)
socket_secret = "{esc(socket_secret)}"
'''
        )
        print(f"\n Config successfully written to {target}")

        if enable_auto:
            from .autostart import enable_autostart
            if enable_autostart():
                print(" Auto-start successfully enabled for your OS!")
            else:
                print(" Failed to configure auto-start. Check logs for details.")

        return 0

    cfg = Config.load(getattr(args, "config", None))

    if args.cmd == "battery":
        from .battery import Battery
        print(Battery().read())
        return 0

    if args.cmd == "doctor":
        from .diagnostics import run_doctor
        success = run_doctor(cfg)
        return 0 if success else 1

    # start: auto-detect role and launch
    if args.cmd == "start":
        env = detect_environment()
        setup_logging(args.verbose, cfg.log_file)

        print("=" * 50)
        print("  Battery Music Notifier - Auto Start")
        print("=" * 50)
        print(f"  Environment: {env.platform_name}")
        print(f"  Local IP:    {env.local_ip or 'not detected'}")
        print(f"  Subnet:      {env.subnet or 'not detected'}")
        print()

        if env.is_termux or env.is_android:
            # Phone: start as client
            print("  Detected: Mobile device (Termux/Android)")
            print("  Role: CLIENT (battery monitor -> sends to laptop)")
            print()
            if env.is_termux:
                print("  Reminder: Run 'termux-wake-lock' to prevent Android from killing the app!")
            print()
            from .remote import RemoteMonitor
            RemoteMonitor(cfg, args.host, args.port).run()
        else:
            # Desktop: start as server
            print("  Detected: Desktop/laptop")
            print("  Role: SERVER (listens for phone commands -> plays music)")
            print()
            from .remote import NotificationServer
            NotificationServer(cfg, args.host, args.port).run()
        return 0

    if args.cmd == "serve":
        setup_logging(args.verbose, cfg.log_file)
        from .remote import NotificationServer
        NotificationServer(cfg, args.host, args.port).run()
        return 0

    if args.cmd == "client":
        setup_logging(args.verbose, cfg.log_file)
        from .remote import RemoteMonitor
        RemoteMonitor(cfg, args.host, args.port).run()
        return 0

    # arm: thief catcher
    if args.cmd == "arm":
        setup_logging(args.verbose, cfg.log_file)
        from .thief_catcher import ThiefCatcher
        from .player import Player

        env = detect_environment()
        print("=" * 50)
        print("  Thief Catcher - Armed Mode")
        print("=" * 50)
        print(f"  Environment: {env.platform_name}")
        print(f"  Mode: {args.mode}")

        # Build worker client if configured
        worker = None
        if cfg.worker_url and args.mode in ("relay", "both"):
            from .worker_client import WorkerClient
            worker = WorkerClient(cfg.worker_url, cfg.worker_token, cfg)
            if not cfg.worker_token:
                print("  No worker token in config. Registering...")
                token = worker.register(device_name=env.platform_name, platform=env.platform_name)
                if token:
                    print(f"  Registered! Token: {token[:8]}... (saved to config)")
                    cfg.worker_token = token
                    # Save token to config file for future use
                    _save_worker_token(token)
                else:
                    print("  [WARN] Registration failed. Using local-only mode.")
                    worker = None
                    args.mode = "local"
        elif not cfg.worker_url and args.mode in ("relay", "both"):
            print("  [WARN] No worker_url configured. Using local-only mode.")
            args.mode = "local"

        # Use alarm_files if set, fall back to music_files
        alarm_files = cfg.alarm_files if cfg.alarm_files else cfg.music_files
        if not alarm_files:
            print("  [ERROR] No alarm sound configured. Run 'battery-music init' first.")
            return 2

        player = Player(alarm_files, cfg.volume, annoying=True)
        tc = ThiefCatcher(cfg, player=player, worker_client=worker, local_port=args.port)

        if args.force:
            info = tc.battery.read()
            print(f"  Battery: {info.percentage}%, charging: {info.charging}")
            print("  --force used: arming even if not charging.")
            print("  Press Ctrl+C to disarm.\n")

        tc.arm(mode=args.mode, verbose=True, force=args.force)
        return 0

    # relay: laptop polls worker for alerts, plays alarm
    if args.cmd == "relay":
        setup_logging(args.verbose, cfg.log_file)
        from .worker_client import WorkerClient
        from .player import Player
        import time as _time

        if not cfg.worker_url:
            print("  [ERROR] No worker_url configured. Run 'battery-music init' first.")
            return 2

        env = detect_environment()
        print("=" * 50)
        print("  Relay Listener (Laptop Side)")
        print("=" * 50)
        print(f"  Environment: {env.platform_name}")
        print(f"  Worker: {cfg.worker_url}")
        print(f"  Polling every 2s for alerts...")
        print("  Press Ctrl+C to stop.\n")

        worker = WorkerClient(cfg.worker_url, cfg.worker_token, cfg)
        if not cfg.worker_token:
            print("  No token. Registering...")
            token = worker.register(device_name=env.platform_name, platform=env.platform_name)
            if token:
                print(f"  Registered! Token: {token[:8]}...")
                cfg.worker_token = token
                _save_worker_token(token)
            else:
                print("  [ERROR] Registration failed.")
                return 1

        alarm_files = cfg.alarm_files if cfg.alarm_files else cfg.music_files
        if not alarm_files:
            print("  [ERROR] No alarm sound configured. Run 'battery-music init' first.")
            return 2

        player = Player(alarm_files, cfg.volume, annoying=True)
        last_alert_active = False
        consecutive_errors = 0

        while True:
            try:
                resp = worker.poll()
                consecutive_errors = 0
                if not resp.get("ok"):
                    error = resp.get("error", "unknown")
                    if error == "unauthorized":
                        print("  [ERROR] Worker rejected token. Re-registering...")
                        token = worker.register(device_name=env.platform_name, platform=env.platform_name)
                        if token:
                            print(f"  Re-registered. New token: {token[:8]}...")
                            cfg.worker_token = token
                            _save_worker_token(token)
                        else:
                            print("  [ERROR] Re-registration failed. Check worker URL and network.")
                    elif error == "banned":
                        print("  [ERROR] Device is banned by admin. Contact admin to resolve.")
                        break
                    else:
                        print(f"  [WARN] Worker poll error: {error}")
                else:
                    alert_active = resp.get("alert_active", 0)
                    alert_type = resp.get("alert_type", "")
                    battery_pct = resp.get("battery_pct", -1)
                    is_charging = resp.get("is_charging", 0)

                    if alert_active and not last_alert_active:
                        print(f"  [{_time.strftime('%H:%M:%S')}] ALERT: {alert_type} (battery={battery_pct}%, charging={is_charging})")
                        player.play()
                        last_alert_active = True
                    elif not alert_active and last_alert_active:
                        print(f"  [{_time.strftime('%H:%M:%S')}] Alert cleared.")
                        player.stop()
                        last_alert_active = False
            except KeyboardInterrupt:
                print("\n  Stopping relay listener...")
                player.stop()
                break
            except Exception as e:
                consecutive_errors += 1
                log.error("Relay poll error: %s", e)
                if consecutive_errors <= 3:
                    print(f"  [WARN] Connection error ({consecutive_errors}): {e}")
                elif consecutive_errors == 10:
                    print("  [ERROR] Worker unreachable after 10 attempts. Check network and worker URL.")
                    print("  Continuing to retry every 2s...")

            _time.sleep(2)
        return 0

    # admin: admin actions
    if args.cmd == "admin":
        from .worker_client import WorkerClient

        if not cfg.worker_url:
            print("  [ERROR] No worker_url configured. Run 'battery-music init' first.")
            return 2

        worker = WorkerClient(cfg.worker_url, config=cfg)

        if args.action == "login":
            if not cfg.admin_key:
                admin_key = input("  Enter admin key: ").strip()
            else:
                admin_key = cfg.admin_key
            session = worker.admin_login(admin_key)
            if session:
                print(f"  Admin login successful. Session: {session[:8]}...")
            else:
                print("  Admin login failed.")
            return 0 if session else 1

        if args.action == "stats":
            # Login first
            if not cfg.admin_key:
                print("  [ERROR] No admin_key configured.")
                return 2
            session = worker.admin_login(cfg.admin_key)
            if not session:
                print("  [ERROR] Admin login failed. Check your admin_key.")
                return 1
            stats = worker.admin_stats()
            if stats.get("ok"):
                s = stats["stats"]
                print(f"\n  Total Users:       {s['total_users']}")
                print(f"  Active (5min):    {s['active_5min']}")
                print(f"  Active Alerts:    {s['active_alerts']}")
                print(f"  Total Alerts:     {s['total_alerts_sent']}")
                print(f"  Pro Users:        {s['pro']}")
                print(f"  Founding:         {s['founding']}")
                print(f"  Banned:           {s['banned']}")
            else:
                print(f"  Error: {stats.get('error')}")
            return 0

        if args.action == "ban":
            if not cfg.admin_key:
                print("  [ERROR] No admin_key configured.")
                return 2
            session = worker.admin_login(cfg.admin_key)
            if not session:
                print("  [ERROR] Admin login failed. Check your admin_key.")
                return 1
            if not args.user_id:
                print("  Usage: battery-music admin ban --user-id 123")
                return 1
            ok = worker.admin_ban(args.user_id)
            print(f"  Banned user {args.user_id}: {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        if args.action == "unban":
            if not cfg.admin_key:
                print("  [ERROR] No admin_key configured.")
                return 2
            session = worker.admin_login(cfg.admin_key)
            if not session:
                print("  [ERROR] Admin login failed. Check your admin_key.")
                return 1
            if not args.user_id:
                print("  Usage: battery-music admin unban --user-id 123")
                return 1
            ok = worker.admin_unban(args.user_id)
            print(f"  Unbanned user {args.user_id}: {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        if args.action == "broadcast":
            if not cfg.admin_key:
                print("  [ERROR] No admin_key configured.")
                return 2
            session = worker.admin_login(cfg.admin_key)
            if not session:
                print("  [ERROR] Admin login failed. Check your admin_key.")
                return 1
            ok = worker.admin_broadcast(args.alert_type)
            print(f"  Broadcast {args.alert_type}: {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        if args.action == "clear":
            if not cfg.admin_key:
                print("  [ERROR] No admin_key configured.")
                return 2
            session = worker.admin_login(cfg.admin_key)
            if not session:
                print("  [ERROR] Admin login failed. Check your admin_key.")
                return 1
            ok = worker.admin_clear_all()
            print(f"  Clear all alerts: {'OK' if ok else 'FAILED'}")
            return 0 if ok else 1

        return 0

    # run: standalone local mode
    if args.music: cfg.music_files = args.music
    if args.min is not None: cfg.min_percentage = args.min
    if args.max is not None: cfg.max_percentage = args.max
    if args.volume is not None: cfg.volume = args.volume
    if args.poll is not None: cfg.poll_interval = args.poll
    if args.annoying: cfg.annoying = True

    setup_logging(args.verbose, cfg.log_file)
    if not cfg.music_files:
        print("No music files configured. Run `battery-music init`")
        return 2

    Monitor(cfg).run()
    return 0
