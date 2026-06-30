from __future__ import annotations
import argparse, sys
from pathlib import Path
from .config import Config, APP_DIR
from .logs import setup_logging
from .monitor import Monitor

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="battery-music", description="Play music when battery reaches target.")
    p.add_argument("-V", "--version", action="version", version="%(prog)s 1.0.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Start monitoring.")
    run.add_argument("-m", "--music", action="append", default=[])
    run.add_argument("--min", type=int)
    run.add_argument("--max", type=int)
    run.add_argument("--volume", type=float)
    run.add_argument("--poll", type=float)
    run.add_argument("--annoying", action="store_true")
    run.add_argument("-v", "--verbose", action="store_true")
    run.add_argument("--config", type=Path)

    sub.add_parser("battery", help="Print current battery info and exit.")
    init = sub.add_parser("init", help="Run setup wizard and write config file.")
    init.add_argument("--force", action="store_true")
    return p

def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    if args.cmd == "init":
        target = APP_DIR / "config.toml"
        if target.exists() and not args.force:
            print(f"Config already exists at {target} (use --force to overwrite)")
            return 1

        print("🎵 Welcome to the Battery Music Notifier setup!")
        music_path = input("Enter path to your music file (e.g., ~/Music/song.wav): ").strip()
        min_pct = input("Enter minimum battery percentage to trigger [99]: ").strip() or "99"
        max_pct = input("Enter maximum battery percentage [100]: ").strip() or "100"
        volume = input("Enter volume 0.0 to 1.0 [0.8]: ").strip() or "0.8"

        APP_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(
            f'''[battery_notifier]
music_files = ["{music_path}"]
min_percentage = {min_pct}
max_percentage = {max_pct}
volume = {volume}
poll_interval = 3.0
annoying = false
quiet_hours = [22, 8]
'''
        )
        print(f"\n✅ Config successfully written to {target}")
        return 0

    cfg = Config.load(getattr(args, "config", None))

    if args.cmd == "battery":
        from .battery import Battery
        print(Battery().read())
        return 0

    # Run command
    if args.music: cfg.music_files = args.music
    # Fix: Clean argument mapping
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
