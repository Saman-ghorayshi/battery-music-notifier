# battery_notifier/diagnostics.py
from __future__ import annotations
import os
import socket
from pathlib import Path
import requests
from .battery import Battery

def run_doctor(cfg) -> bool:
    """Runs a live pre-flight validation scan on hardware, config, and proxy endpoints."""
    print("🔬 Running Battery Music Notifier System Diagnostics...\n")
    all_clear = True

    print("🎵 [Checking Audio Assets]")
    if not cfg.music_files:
        print("   No music files registered. Run `battery-music init` first.")
        all_clear = False
    else:
        for f in cfg.music_files:
            p = Path(os.path.expanduser(f))
            if p.exists():
                print(f"   Located: {p.name}")
            else:
                print(f"   Missing Track: File does not exist at '{p}'")
                all_clear = False
    print("\n [Checking Battery Telemetry Engine]")
    try:
        b = Battery()
        info = b.read()
        print(f"   Telemetry Online (Current Battery: {info.percentage}%, Charging: {info.charging})")
        
        # Termux specific warning
        import shutil
        if shutil.which("termux-battery-status"):
            print("   ⚠️ ANDROID TERMUX DETECTED: You MUST run 'termux-wake-lock' before starting the client,")
            print("      otherwise Android will kill the app when your screen turns off!")
    except Exception as err:
        print(f"  {err}")
        all_clear = False

    print("\n [Checking Proxy Configurations & Local Ports]")
    if cfg.proxy_url:
        if not (cfg.proxy_url.startswith("http://") or cfg.proxy_url.startswith("socks5://")):
            print("   Malformed proxy_url setting. Must specify a valid protocol (e.g., http:// or socks5://)")
            all_clear = False
        else:
            print(f"  Configured Proxy Routing: {cfg.proxy_url}")
    else:
        print("  config.toml is set to Direct Connection routing (No proxy configured).")
        #added some apps if you know more add them
        common_proxy_ports = {
            12334: "socks5://127.0.0.1:12334 (Hiddify Mixed Proxy Default)",
            10808: "socks5://127.0.0.1:10808 (v2rayN SOCKS5 Core)",
            10809: "http://127.0.0.1:10809 (v2rayN HTTP Companion)",
            7890:  "http://127.0.0.1:7890 (Clash / Mihomo Local Host)",
            2080:  "socks5://127.0.0.1:2080 (Nekoray / Sing-box Inbound Core)",
            1080:  "socks5://127.0.0.1:1080 (Classic Shadowsocks / SOCKS5 Client)",
            1081:  "socks5://127.0.0.1:1081 (Alternative V2Ray Client Default)"
        }
        
        detected_listeners = []
        for port, description in common_proxy_ports.items():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    detected_listeners.append(description)
        
        if detected_listeners:
            print("\n  DETECTED ACTIVE LOCAL PROXIES (Not linked to your config):")
            for listener in detected_listeners:
                print(f"     Active client found running at: {listener}")
            print("\n   TIP: Since Telegram is blocked natively, you MUST bind one of these to your configuration!")
            print("     Run `battery-music init --force` and paste one of the addresses above into your proxy field.")

    print("\n [Testing Live Web Connection Status]")
    proxies = {"http": cfg.proxy_url, "https": cfg.proxy_url} if cfg.proxy_url else {}
    
    try:
        r = requests.head("https://www.google.com", proxies=proxies, timeout=4)
        print(f"   Global Web Backbone: Available (Google responded with Status {r.status_code})")
    except Exception:
        print("   Global Web Backbone: Unreachable. Your computer is offline or your proxy configuration is wrong.")
        all_clear = False


    try:
        r = requests.head("https://api.telegram.org", proxies=proxies, timeout=4)
        #  Included 302 since Telegram roots natively redirect to documentation
        if r.status_code in (200, 302, 404):
            print("   Telegram API Gateway: Fully Reachable!")
        else:
            print(f"   Telegram API Gateway: Returned unexpected status code {r.status_code}.")
            all_clear = False  
    except Exception:
        print("   Telegram API Gateway: UNREACHABLE!")
        print("     Reason: Blocked by local ISP/Government censorship firewall rules.")
        if not cfg.proxy_url:
            print("     FIX: You must configure an active SOCKS5/HTTP proxy inside your config.toml file.")
        all_clear = False
    # Final Diagnostic Summary Layout
    print("\n" + "="*60)
    if all_clear:
        print(" DIAGNOSTICS PASSED: Environment looks perfect to execute!")
    else:
        print("DIAGNOSTICS FAILED: Please fix the blocking issues listed above.")
    print("="*60)

    return all_clear