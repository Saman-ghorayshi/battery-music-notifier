# Battery Music Notifier

Play music when your battery reaches a target percentage. Designed for a two-device setup: your phone (Termux) monitors battery and sends commands, your laptop plays the sound.

The script auto-detects its environment, finds the server, handles VPNs, auto-discovers proxies, and falls back to Telegram cloud when local networks fail.

---

## Quick Start

On both your laptop and your phone, just run:

```bash
battery-music start
```

That's it. The script figures out its own role:
- **Termux/Android** -> starts as client (battery monitor, sends commands)
- **Desktop/Laptop** -> starts as server (listens for commands, plays music)

No manual IP configuration needed. The client auto-discovers the server through up to 4 methods.

---

## Installation

### Android (Termux)

```bash
pkg update && pkg upgrade -y
pkg install python termux-api mpv git -y
git clone <your-repo-url>
cd batterytest
pip install -e .
```

You also need the **Termux:API** app from F-Droid or Google Play.

### Windows / macOS / Linux

```bash
git clone <your-repo-url>
cd batterytest
pip install -e .
```

---

## Setup Wizard

Run the setup wizard to select music, set thresholds, and configure notifications:

```bash
battery-music init
```

Reconfigure later with `battery-music init --force`.

### Email (SMTP) Alerts
1. Google Account -> Security -> enable 2-Step Verification
2. Create an App Password for "Battery Notifier"
3. Enter the 16-character code when the wizard asks for `email_password`
4. Port 465 = SSL, Port 587 = TLS (auto-detected)

### Telegram Cloud Fallback
1. Message `@BotFather` -> `/newbot` -> copy the Bot Token
2. Message `@userinfobot` -> copy your Chat ID
3. Enter both into the wizard

The laptop polls the bot's description field for START/STOP commands. The phone updates the description, the laptop reads it. No API ID/Hash needed.

---

## Commands

| Command | Description |
|---|---|
| `battery-music start` | Auto-detect role and start (one command for both devices) |
| `battery-music serve` | Start as server only (laptop side) |
| `battery-music client` | Start as client only (phone side) |
| `battery-music run` | Standalone local monitoring (single device) |
| `battery-music init` | Run setup wizard |
| `battery-music doctor` | Full system diagnostics |
| `battery-music battery` | Print current battery status |
| `battery-music start --port 9000` | Use a custom port |

---

## How Connection Works

The client tries 4 methods to find the server, fastest first:

```
[1/4] USB ADB tunnel (127.0.0.1)  -- works even under VPN
[2/4] UDP beacon broadcast         -- Wi-Fi/hotspot auto-discovery
[3/4] Cached last-known-good IP    -- from ~/.config/battery-music-notifier/last_server.json
[4/4] Subnet scan (concurrent)     -- probes all 254 IPs in /24, PING-verified
```

Each candidate is verified with a PING/PONG health check before being accepted. If the server is found, the client connects and sends START/STOP commands. The server sends back an ACK confirmation so the client knows the command was received.

### If all local methods fail

The client checks if it has internet access. If yes, it falls back to the **Telegram Cloud** method: it updates the bot's description to "START"/"STOP", and the laptop (which is polling the bot) picks it up and plays/stops the music.

---

## VPN Detection

The script detects active VPNs by checking for virtual network interfaces:

- **Android/Termux**: scans `/sys/class/net` for `tun*`, `tap*`, `ppp*` interfaces
- **Windows**: checks PowerShell for Wintun, TAP, WireGuard, OpenVPN adapters
- **Linux/macOS**: checks `ip link` / `ifconfig` for tunnel interfaces

When a VPN is detected:
- UDP beacon discovery is skipped (VPN blocks broadcast)
- Subnet scan is skipped (VPN isolates from local network)
- USB ADB tunnel still works (it's a physical wire, not network)
- Cached IP is still tried
- If all local methods fail, **Telegram cloud fallback** activates automatically
- VPN status is printed at startup

---

## Auto-Proxy Detection

If you have a VPN or proxy client running (v2rayN, Hiddify, Clash, Nekoray, etc.) but forgot to configure `proxy_url` in your config, the script will:

1. Scan common proxy ports on 127.0.0.1 at startup
2. Auto-apply the first working proxy to all Telegram/HTTP requests
3. Print which proxy was detected and applied

Ports scanned:

| Port | Protocol | Client |
|---|---|---|
| 12334 | SOCKS5 | Hiddify (Mixed) |
| 10808 | SOCKS5 | v2rayN (SOCKS5) |
| 10809 | HTTP | v2rayN (HTTP) |
| 7890 | HTTP | Clash / Mihomo |
| 2080 | SOCKS5 | Nekoray / Sing-box |
| 1080 | SOCKS5 | Shadowsocks |
| 1081 | SOCKS5 | Alt V2Ray |

Priority: if you set `proxy_url` in config, that takes priority over auto-detected.

---

## ACK Protocol

Every command is confirmed:

```
Client -> Server:  "START"
Server -> Client:  "ACK:START"
```

If the server doesn't ACK within 5 seconds, the client retries. After 3 consecutive failures, the client resets and switches to Telegram cloud fallback.

The server also answers `PING` with `PONG` for health checks, so the client can verify a found server is actually our server (not some random open port).

---

## Diagnostics

Run a full system check:

```bash
battery-music doctor
```

This shows:
1. Environment (platform, local IP, subnet)
2. VPN status
3. Proxy configuration + auto-detected proxies
4. Audio assets
5. Battery telemetry
6. Network connectivity (Google, Telegram API)
7. Server reachability (PING test)

---

## Deployment Scenarios

### Scenario A: One-command (Recommended)

On laptop:
```bash
battery-music start
```
On phone:
```bash
termux-wake-lock
battery-music start
```

### Scenario B: USB Cable

On laptop:
```bash
battery-music serve
```
On phone:
```bash
battery-music client --host 127.0.0.1
```

The ADB reverse tunnel is set up automatically when the server starts.

### Scenario C: Wi-Fi / Hotspot

On laptop:
```bash
battery-music serve
```
On phone:
```bash
battery-music client
```
(Host defaults to "auto", triggering UDP beacon + subnet scan discovery)

### Scenario D: VPN Active + No USB

When a VPN is detected and no USB cable is connected, local discovery is skipped. The client goes straight to Telegram cloud fallback:

1. Phone detects battery threshold
2. Phone updates bot description to "START" via Telegram API
3. Laptop polls bot description, sees "START", plays music
4. Phone updates description to "STOP" when battery normalizes

The auto-proxy detection ensures Telegram API calls go through your local proxy client even if you forgot to configure it.

---

## Termux Wake Lock

Android kills background apps when the screen turns off. You MUST acquire a wake lock:

```bash
termux-wake-lock
```

Run `termux-wake-release` when done.

---

## Troubleshooting

- **Music doesn't play on Termux**: Install `mpv` (`pkg install mpv`) and grant storage access (`termux-setup-storage`).
- **Client can't find server**: Run `battery-music doctor` on both devices. Check that server shows "Listening on 0.0.0.0:8000" and the client shows your laptop's local IP.
- **VPN blocks discovery**: Use a USB cable (`--host 127.0.0.1`) or rely on Telegram cloud fallback. The script will tell you when VPN is detected.
- **Telegram fails on Termux**: Your Android VPN is routing traffic poorly. The auto-proxy detection should handle this, but you can manually set `proxy_url` in config.
- **Laptop doesn't receive Telegram command**: Ensure you're using the Bot Description trick (built-in automatically). A bot cannot read its own messages in a standard chat.
- **Email fails with SSL Error**: Use an App Password, not your standard Gmail password. Port 465 for SSL, 587 for TLS.
- **Port 8000 is taken**: Use `--port 8001` or any free port on both server and client.

---

## Project Structure

```
battery_notifier/
  __init__.py       Package metadata
  __main__.py       Entry point (python -m battery_notifier)
  cli.py            CLI argument parser + start command auto-detection
  config.py         Config dataclass + proxy URL sanitizer
  connection.py     Environment/VPN/proxy detection, server discovery, ACK protocol
  remote.py         NotificationServer + RemoteMonitor (client/server logic)
  battery.py        Cross-platform battery reader (psutil + Termux)
  player.py         Audio player (sounddevice -> mpv -> ffplay fallback chain)
  notifier.py       OS-level notifications (Windows toast, macOS, Linux)
  adb_helper.py     USB ADB bridge auto-setup
  autostart.py      Boot auto-start (Windows VBS / Linux .desktop)
  diagnostics.py    Full system diagnostic scan
  logs.py           Logging setup
tests/
  test_battery.py   40 tests: PING/PONG, ACK, cache, bind, subnet scan, VPN, proxy
```

---

## License

MIT
