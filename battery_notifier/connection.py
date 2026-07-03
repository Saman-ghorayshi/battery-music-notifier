# battery_notifier/connection.py
"""Smart networking layer: environment detection, VPN detection,
auto-proxy discovery, server discovery, ACK protocol."""
from __future__ import annotations
import os
import json
import time
import socket
import shutil
import logging
import platform
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)

# UDP discovery constants
DISCOVERY_UDP_PORT = 8002
BEACON_MESSAGE = b"BATTERY_MUSIC_BEACON_V1"

# ACK protocol constants
ACK_PREFIX = "ACK:"

# Cache file for last-known-good server address
_CACHE_DIR = Path(
    os.environ.get("BATTERY_NOTIFIER_HOME", Path.home() / ".config" / "battery-music-notifier")
)
CACHE_FILE = _CACHE_DIR / "last_server.json"

# Subnet scan tuning
_SCAN_CONNECT_TIMEOUT = 0.1
_SCAN_PING_TIMEOUT = 0.4
_SCAN_BATCH_SIZE = 32

# Common proxy ports used by v2rayN, Hiddify, Clash, Nekoray, etc.
COMMON_PROXY_PORTS = {
    12334: "socks5://127.0.0.1:12334",
    10808: "socks5://127.0.0.1:10808",
    10809: "http://127.0.0.1:10809",
    7890:  "http://127.0.0.1:7890",
    2080:  "socks5://127.0.0.1:2080",
    1080:  "socks5://127.0.0.1:1080",
    1081:  "socks5://127.0.0.1:1081",
}


@dataclass
class Environment:
    """Detected runtime environment and network info."""
    is_termux: bool
    is_android: bool
    is_windows: bool
    is_linux: bool
    is_macos: bool
    platform_name: str
    local_ip: Optional[str]
    subnet: Optional[str]
    is_vpn: bool
    vpn_name: Optional[str]
    auto_proxy: Optional[str]


def detect_environment() -> Environment:
    """Detect the current runtime environment, VPN status, and local proxies."""
    is_termux = (
        "TERMUX_VERSION" in os.environ
        or bool(shutil.which("termux-battery-status"))
    )
    is_android = is_termux or "ANDROID_ROOT" in os.environ
    sys_name = platform.system()
    is_windows = sys_name == "Windows"
    is_linux = sys_name == "Linux" and not is_android
    is_macos = sys_name == "Darwin"

    local_ip = _get_local_ip()
    subnet = _get_subnet(local_ip)

    # VPN detection
    is_vpn, vpn_name = _detect_vpn(is_termux, is_android, is_windows, is_linux, is_macos)

    # Auto-proxy detection: scan for running local proxies
    auto_proxy = _detect_local_proxy()

    if is_termux:
        label = "Termux (Android)"
    elif is_windows:
        label = "Windows"
    elif is_macos:
        label = "macOS"
    elif is_linux:
        label = "Linux"
    else:
        label = sys_name

    return Environment(
        is_termux=is_termux,
        is_android=is_android,
        is_windows=is_windows,
        is_linux=is_linux,
        is_macos=is_macos,
        platform_name=label,
        local_ip=local_ip,
        subnet=subnet,
        is_vpn=is_vpn,
        vpn_name=vpn_name,
        auto_proxy=auto_proxy,
    )


def _get_local_ip() -> Optional[str]:
    """Get local IP by opening a UDP socket to a public address (no data sent)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _get_subnet(ip: Optional[str]) -> Optional[str]:
    """Derive /24 subnet prefix from an IP like 192.168.1.42 -> 192.168.1."""
    if not ip:
        return None
    parts = ip.split(".")
    if len(parts) != 4:
        return None
    return ".".join(parts[:3])


# ---------------------------------------------------------------------------
# VPN detection
# ---------------------------------------------------------------------------

def _detect_vpn(
    is_termux: bool, is_android: bool,
    is_windows: bool, is_linux: bool, is_macos: bool,
) -> tuple[bool, Optional[str]]:
    """
    Detect if a VPN is active by checking network interfaces.
    Returns (is_vpn, vpn_name_or_None).

    VPNs typically create virtual interfaces named: tun*, tap*, ppp*,
    or on Windows: specific adapter names like "Wintun" or "TAP-Windows".
    """
    # Termux/Android: check for VPN-like interfaces in /sys/class/net
    if is_termux or is_android:
        return _detect_vpn_android()

    if is_windows:
        return _detect_vpn_windows()

    # Linux/macOS: check network interfaces
    return _detect_vpn_unix()


def _detect_vpn_android() -> tuple[bool, Optional[str]]:
    """Check Android network interfaces for VPN tunnels."""
    try:
        interfaces = os.listdir("/sys/class/net")
        for iface in interfaces:
            # VPN apps create tun0, tap0, ppp0, or use names like "vpn_tun"
            lower = iface.lower()
            if lower.startswith(("tun", "tap", "ppp")):
                return True, iface
            # Some VPN apps use specific names
            if "vpn" in lower and lower != "vpn":
                return True, iface
    except Exception:
        pass
    return False, None


def _detect_vpn_windows() -> tuple[bool, Optional[str]]:
    """Detect VPN on Windows via PowerShell or ipconfig."""
    # Try PowerShell first for adapter names
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "Get-NetAdapter | Where-Object {$_.InterfaceDescription -match 'Wintun|TAP|VPN|WireGuard|OpenVPN|Hamachi|ZeroTier'} | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=5,
        )
        names = [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
        if names:
            return True, names[0]
    except Exception:
        pass

    # Fallback: ipconfig
    try:
        result = subprocess.run(
            ["ipconfig", "/all"], capture_output=True, text=True, timeout=5
        )
        output = result.stdout.lower()
        vpn_keywords = ["wintun", "tap-windows", "openvpn", "wireguard", "vpn adapter"]
        for kw in vpn_keywords:
            if kw in output:
                return True, kw
    except Exception:
        pass
    return False, None


def _detect_vpn_unix() -> tuple[bool, Optional[str]]:
    """Detect VPN on Linux/macOS by checking network interfaces."""
    try:
        result = subprocess.run(
            ["ip", "link", "show"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            # Lines look like: "2: eth0: <BROADCAST..." or "5: tun0: <..."
            if ": " in line:
                iface = line.split(": ")[1].split(":")[0].strip().split("@")[0]
                lower = iface.lower()
                if lower.startswith(("tun", "tap", "ppp")) or "vpn" in lower:
                    return True, iface
    except Exception:
        pass

    # macOS fallback: ifconfig
    try:
        result = subprocess.run(
            ["ifconfig"], capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.split("\n"):
            line = line.strip()
            if line and not line.startswith("\t") and ":" in line:
                iface = line.split(":")[0].strip().lower()
                if iface.startswith(("tun", "tap", "ppp", "utun", "ipsec")) or "vpn" in iface:
                    return True, iface
    except Exception:
        pass
    return False, None


# ---------------------------------------------------------------------------
# Auto-proxy detection
# ---------------------------------------------------------------------------

def _detect_local_proxy() -> Optional[str]:
    """
    Scan common proxy ports on 127.0.0.1 concurrently.
    Returns the first working proxy URL found, or None.
    Uses threads to avoid 1.4s sequential delay on startup.
    Verifies the port is actually a proxy (not just any listening service)
    by sending an HTTP CONNECT and checking for a proxy-style response.
    """
    import concurrent.futures

    def check_port(port: int, proxy_url: str) -> Optional[str]:
        # Step 1: is anything listening?
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.1)
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return None

        # Step 2: verify it's a proxy (not some unrelated service)
        # HTTP proxies respond to HTTP CONNECT with "HTTP/1.x ..."
        # SOCKS5 proxies respond to 0x05 (version byte) with 0x05 0x00
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                s.connect(("127.0.0.1", port))
                if proxy_url.startswith("socks5://"):
                    # SOCKS5 handshake: version=5, methods=1, no-auth=0
                    s.sendall(b"\x05\x01\x00")
                    resp = s.recv(2)
                    # Valid SOCKS5 response: version=5, selected method=0x00 (no auth)
                    if len(resp) >= 2 and resp[0] == 0x05:
                        return proxy_url
                else:
                    # HTTP proxy: send CONNECT, check for HTTP response line
                    s.sendall(b"CONNECT 127.0.0.1:1 HTTP/1.1\r\nHost: 127.0.0.1:1\r\n\r\n")
                    resp = s.recv(256)
                    if resp.startswith(b"HTTP/"):
                        return proxy_url
        except Exception:
            pass
        return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(COMMON_PROXY_PORTS)) as executor:
        futures = {
            executor.submit(check_port, p, u): u
            for p, u in COMMON_PROXY_PORTS.items()
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                log.info("Auto-detected local proxy: %s", result)
                executor.shutdown(wait=False, cancel_futures=True)
                return result
    return None


def get_effective_proxy(config) -> Optional[str]:
    """
    Determine which proxy to actually use at runtime.
    Priority: config.proxy_url > auto-detected proxy > None.

    If config has a proxy explicitly set, use that.
    Otherwise, auto-detect and use the first available local proxy.
    """
    if config and config.proxy_url:
        return config.proxy_url
    env = detect_environment()
    return env.auto_proxy


# ---------------------------------------------------------------------------
# Server verification (PING/PONG)
# ---------------------------------------------------------------------------

def ping_server(host: str, port: int, timeout: float = 2.0) -> bool:
    """Send PING to server and check for PONG response. Verifies it's our server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(b"PING")
            resp = s.recv(1024).decode("utf-8").strip()
            return resp == "PONG"
    except Exception as e:
        log.debug("PING to %s:%d failed: %s", host, port, e)
        return False


# ---------------------------------------------------------------------------
# Discovery methods
# ---------------------------------------------------------------------------

def discover_server_udp(timeout: float = 4.0) -> Optional[str]:
    """Listen for UDP beacon broadcast from the laptop server."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            s.bind(("", DISCOVERY_UDP_PORT))
            s.settimeout(timeout)
            start = time.time()
            while time.time() - start < timeout:
                try:
                    data, addr = s.recvfrom(1024)
                    if data == BEACON_MESSAGE:
                        log.info("UDP beacon received from %s", addr[0])
                        return addr[0]
                except socket.timeout:
                    break
                except Exception:
                    pass
    except Exception as e:
        log.debug("UDP discovery failed: %s", e)
    return None


def scan_subnet(port: int, subnet: Optional[str]) -> Optional[str]:
    """
    Concurrently scan all IPs in the /24 subnet for our server.
    Each open port is verified with PING/PONG to avoid false positives.
    """
    if not subnet:
        return None

    found_ip: Optional[str] = None
    lock = threading.Lock()

    def _probe(ip: str) -> None:
        nonlocal found_ip
        if found_ip:
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(_SCAN_CONNECT_TIMEOUT)
                if s.connect_ex((ip, port)) != 0:
                    return
                s.settimeout(_SCAN_PING_TIMEOUT)
                s.sendall(b"PING")
                resp = s.recv(1024).decode("utf-8").strip()
                if resp == "PONG":
                    with lock:
                        found_ip = ip
        except Exception:
            pass

    threads: list[threading.Thread] = []
    for i in range(1, 255):
        ip = f"{subnet}.{i}"
        t = threading.Thread(target=_probe, args=(ip,), daemon=True)
        threads.append(t)
        t.start()
        if len(threads) >= _SCAN_BATCH_SIZE:
            for t2 in threads:
                t2.join(timeout=_SCAN_CONNECT_TIMEOUT + _SCAN_PING_TIMEOUT + 0.5)
            threads = [t for t in threads if t.is_alive()]
            if found_ip:
                break

    for t in threads:
        t.join(timeout=_SCAN_CONNECT_TIMEOUT + _SCAN_PING_TIMEOUT + 0.5)

    if found_ip:
        log.info("Subnet scan found server at %s", found_ip)
    return found_ip


def load_cached_host() -> Optional[str]:
    """Load last-known-good server address from cache file."""
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text())
            return data.get("host")
    except Exception:
        pass
    return None


def save_cached_host(host: str) -> None:
    """Save a working server address to cache for next session."""
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps({"host": host, "ts": time.time()}))
    except Exception as e:
        log.debug("Failed to cache host: %s", e)


def smart_find_server(port: int = 8000, verbose: bool = False) -> Optional[str]:
    """
    Try multiple methods to find the server, fastest first:
      1. USB ADB reverse tunnel (127.0.0.1)
      2. UDP beacon broadcast
      3. Cached last-known-good IP
      4. Subnet scan (concurrent TCP + PING verify)

    If a VPN is detected, local discovery methods 2 and 4 are skipped
    (VPN isolates the device from the local network), and the function
    goes straight to Telegram cloud fallback by returning None.
    """
    env = detect_environment()

    def _log(msg: str) -> None:
        if verbose:
            print(msg)

    # VPN detection: warn and skip network-local methods
    if env.is_vpn:
        _log(f"  [VPN] VPN detected ({env.vpn_name}). Local network discovery will be limited.")

        # Method 1: USB ADB tunnel still works under VPN (it's a USB wire, not network)
        _log("  [1/4] Checking USB tunnel (127.0.0.1)...")
        if ping_server("127.0.0.1", port, timeout=1.0):
            _log("  -> USB tunnel active (works under VPN)")
            save_cached_host("127.0.0.1")
            return "127.0.0.1"

        # Method 3: cached IP might still work if both devices share the VPN
        _log("  [3/4] Checking cached address...")
        cached = load_cached_host()
        if cached and cached != "127.0.0.1":
            if ping_server(cached, port, timeout=1.5):
                _log(f"  -> Cached host still alive: {cached}")
                return cached
            _log(f"  -> Cached host {cached} is stale")

        _log("  -> VPN isolates local network. Skipping UDP beacon + subnet scan.")
        _log("  -> Use USB cable or Telegram cloud fallback.")
        return None

    # Normal discovery (no VPN)
    # Method 1: USB ADB reverse tunnel
    _log("  [1/4] Checking USB tunnel (127.0.0.1)...")
    if ping_server("127.0.0.1", port, timeout=1.0):
        _log("  -> USB tunnel active (127.0.0.1 responded to PING)")
        save_cached_host("127.0.0.1")
        return "127.0.0.1"

    # Method 2: UDP beacon
    _log("  [2/4] Listening for UDP beacon...")
    candidate = discover_server_udp(timeout=3.0)
    if candidate:
        if ping_server(candidate, port, timeout=1.5):
            _log(f"  -> Beacon found and verified: {candidate}")
            save_cached_host(candidate)
            return candidate
        _log(f"  -> Beacon found at {candidate} but PING failed, skipping")

    # Method 3: Cached last-known-good IP
    _log("  [3/4] Checking cached address...")
    cached = load_cached_host()
    if cached and cached != "127.0.0.1":
        if ping_server(cached, port, timeout=1.5):
            _log(f"  -> Cached host still alive: {cached}")
            return cached
        _log(f"  -> Cached host {cached} is stale")

    # Method 4: Subnet scan
    if env.subnet:
        _log(f"  [4/4] Scanning subnet {env.subnet}.0/24 (concurrent)...")
        candidate = scan_subnet(port, env.subnet)
        if candidate:
            _log(f"  -> Subnet scan found server: {candidate}")
            save_cached_host(candidate)
            return candidate
    else:
        _log("  [4/4] Subnet scan skipped (no local IP detected)")

    _log("  -> All discovery methods failed.")
    return None


# ---------------------------------------------------------------------------
# Server-side: smart bind
# ---------------------------------------------------------------------------

def smart_bind_server(host: str, port: int) -> Optional[socket.socket]:
    """
    Try to bind the server socket. If host is 'auto', try 0.0.0.0 then 127.0.0.1.
    Returns the bound listening socket or None.
    """
    if host.lower() == "auto":
        hosts_to_try = ["0.0.0.0", "127.0.0.1"]
    else:
        hosts_to_try = [host]

    for h in hosts_to_try:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((h, port))
            s.listen()
            s.settimeout(1.0)
            log.info("Server bound to %s:%d", h, port)
            return s
        except OSError as e:
            log.warning("Failed to bind %s:%d: %s", h, port, e)
            try:
                s.close()
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Client-side: send command with ACK
# ---------------------------------------------------------------------------

def send_command_with_ack(
    host: str, port: int, command: str, timeout: float = 5.0,
    secret: str = "",
) -> bool:
    """
    Send a command (START/STOP/THIEF_ALERT/THIEF_STOP) to the server and wait
    for ACK confirmation. Returns True only if the server acknowledged.

    If a shared secret is provided, the command is prefixed as "SECRET:command"
    for server-side authentication.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            if secret:
                payload = f"{secret}:{command}".encode("utf-8")
            else:
                payload = command.encode("utf-8")
            s.sendall(payload)
            try:
                ack = s.recv(1024).decode("utf-8").strip()
                expected = f"{ACK_PREFIX}{command}"
                if ack == expected:
                    return True
                log.warning("Unexpected ACK response: %s (expected %s)", ack, expected)
            except socket.timeout:
                log.warning("Server did not ACK within %.1fs", timeout)
            return False
    except Exception as e:
        log.error("Connection to %s:%d failed: %s", host, port, e)
        return False
