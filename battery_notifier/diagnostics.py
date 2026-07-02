# battery_notifier/diagnostics.py
from __future__ import annotations
import os
import socket
from pathlib import Path
import requests
from .battery import Battery
from .connection import (
    detect_environment,
    ping_server,
    load_cached_host,
    get_effective_proxy,
    COMMON_PROXY_PORTS,
)


def run_doctor(cfg) -> bool:
    """Run a full pre-flight diagnostic scan: environment, VPN, proxy, audio, battery, network."""
    env = detect_environment()

    print("=" * 55)
    print("  Battery Music Notifier - System Diagnostics")
    print("=" * 55)

    all_clear = True

    # -- 1. Environment Info --
    print("\n [1] Environment Detection")
    print(f"   Platform:       {env.platform_name}")
    print(f"   Is Termux:      {env.is_termux}")
    print(f"   Is Android:     {env.is_android}")
    print(f"   Is Windows:     {env.is_windows}")
    print(f"   Is Linux:       {env.is_linux}")
    print(f"   Is macOS:       {env.is_macos}")
    print(f"   Local IP:       {env.local_ip or 'not detected'}")
    print(f"   Subnet (/24):   {env.subnet or 'not detected'}")
    print(f"   Cached Host:    {load_cached_host() or 'none'}")

    if env.is_termux:
        print("   Note: Running on Termux. Run 'termux-wake-lock' before client mode!")

    # -- 2. VPN Detection --
    print("\n [2] VPN Detection")
    if env.is_vpn:
        print(f"   VPN ACTIVE:     {env.vpn_name}")
        print("   Impact: Local network discovery (UDP beacon, subnet scan) will be skipped.")
        print("   Impact: ADB USB tunnel and cached IP still work.")
        print("   Impact: Telegram cloud fallback will be used if local methods fail.")
    else:
        print("   No VPN detected. All discovery methods available.")

    # -- 3. Proxy Configuration --
    print("\n [3] Proxy Configuration")
    effective_proxy = get_effective_proxy(cfg)

    if cfg.proxy_url:
        # Validate format
        if not (cfg.proxy_url.startswith("http://") or cfg.proxy_url.startswith("socks5://")):
            print(f"   MALFORMED: {cfg.proxy_url} (must start with http:// or socks5://)")
            all_clear = False
        else:
            print(f"   Configured:    {cfg.proxy_url}")
    else:
        print("   No proxy in config.")

    if env.auto_proxy:
        if cfg.proxy_url:
            print(f"   Auto-detected: {env.auto_proxy} (not used, config takes priority)")
        else:
            print(f"   Auto-detected: {env.auto_proxy}")
            print("   -> This proxy will be AUTO-APPLIED at runtime (no config needed)")
    else:
        print("   Auto-detected: none (no local proxy found on common ports)")

    if effective_proxy:
        print(f"   Effective:     {effective_proxy} (this is what will be used)")
    else:
        print("   Effective:     none (direct connection)")

    # Scan all common proxy ports for info
    detected_proxies = []
    for port, desc in COMMON_PROXY_PORTS.items():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                detected_proxies.append(f"{desc} (port {port})")
    if detected_proxies:
        print(f"   All open proxy ports: {', '.join(str(p) for p in detected_proxies)}")

    # -- 4. Audio Assets --
    print("\n [4] Audio Assets")
    if not cfg.music_files:
        print("   No music files registered. Run `battery-music init` first.")
        all_clear = False
    else:
        for f in cfg.music_files:
            p = Path(os.path.expanduser(f))
            if p.exists():
                print(f"   OK: {p.name}")
            else:
                print(f"   MISSING: {p}")
                all_clear = False

    # -- 5. Battery Telemetry --
    print("\n [5] Battery Telemetry")
    try:
        b = Battery()
        info = b.read()
        print(f"   OK: {info.percentage}%, charging={info.charging}")
    except Exception as err:
        print(f"   FAIL: {err}")
        all_clear = False

    # -- 6. Network Connectivity --
    print("\n [6] Network Connectivity")
    proxies = {"http": effective_proxy, "https": effective_proxy} if effective_proxy else {}

    # Google
    try:
        r = requests.head("https://www.google.com", proxies=proxies, timeout=4)
        print(f"   Google:          reachable (HTTP {r.status_code})")
    except Exception:
        print("   Google:          UNREACHABLE (offline or proxy broken)")
        all_clear = False

    # Telegram API
    try:
        r = requests.head("https://api.telegram.org", proxies=proxies, timeout=4)
        if r.status_code in (200, 302, 404):
            print(f"   Telegram API:    reachable (HTTP {r.status_code})")
        else:
            print(f"   Telegram API:    unexpected status {r.status_code}")
            all_clear = False
    except Exception:
        print("   Telegram API:    UNREACHABLE (blocked by firewall/ISP)")
        if not effective_proxy:
            print("     FIX: Configure a proxy or run a local proxy client (v2rayN, Hiddify, etc.)")
        all_clear = False

    # -- 7. Server Reachability --
    print("\n [7] Server Reachability")
    cached = load_cached_host()
    test_hosts = []
    if cached:
        test_hosts.append(("cached", cached))
    test_hosts.append(("localhost", "127.0.0.1"))
    if env.local_ip:
        test_hosts.append(("local-ip", env.local_ip))

    server_found = False
    for label, host in test_hosts:
        if ping_server(host, 8000, timeout=1.0):
            print(f"   {label} ({host}:8000): ALIVE (responded to PING)")
            server_found = True
        else:
            print(f"   {label} ({host}:8000): no response")

    if not server_found:
        print("   No server detected. Run `battery-music serve` on the laptop first.")

    # -- Summary --
    print("\n" + "=" * 55)
    if all_clear:
        print("  DIAGNOSTICS PASSED: Environment looks good!")
    else:
        print("  DIAGNOSTICS FAILED: Fix the issues listed above.")
    print("=" * 55)

    return all_clear
