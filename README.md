# Battery Music Notifier

A cross-platform battery monitor and thief catcher. Works on your phone (Termux) and laptop (Windows/macOS/Linux). Three ways to connect: Cloudflare Worker relay (default, zero config), local socket (USB/Wi-Fi), or Telegram cloud fallback.

## What It Does

1. **Battery Notifier** -- Phone monitors battery. When it hits your threshold (low or full), the laptop plays a sound.
2. **Thief Catcher** -- Arm it while charging. If someone unplugs the charger, both the phone and laptop scream immediately.

---

## Quick Start

### Install

**Android (Termux):**
```bash
pkg update && pkg upgrade -y
pkg install python termux-api mpv git -y
git clone <your-repo-url>
cd batterytest
pip install -e .
```
Install the **Termux:API** app from F-Droid or Google Play.

**Windows / macOS / Linux:**
```bash
git clone <your-repo-url>
cd batterytest
pip install -e .
```

### Run

On laptop:
```bash
battery-music relay
```

On phone:
```bash
termux-wake-lock
battery-music arm
```

That's it. The app connects to the default hosted worker relay automatically. A bundled alarm sound is included. No configuration needed.

Want to pick your own music or change thresholds?
```bash
battery-music init
```

---

## Connection Tiers

The app supports three connection methods. Use whatever fits your situation.

### Tier 1: Cloudflare Worker Relay (Default)

Best for most users. Both devices just need internet. No local network, no USB cable, no IP configuration.

- **Hosted worker**: Pre-configured, works out of the box. Just install and run. Rate-limited (30 req/min/user) to protect the server. THIEF_ALERT always bypasses rate limiting.
- **Self-hosted worker**: For users who want privacy or no rate limits. Deploy your own worker (see `worker/README.md`), then enter your URL during `battery-music init`.

The worker uses a D1 database (SQLite), handles 10k-50k users, and includes an admin dashboard at `/admin`.

**Battery notifier over relay:**
```bash
# Laptop (listens for alerts, plays sound)
battery-music relay

# Phone (monitors battery, sends alerts to worker)
battery-music start
```

**Thief catcher over relay:**
```bash
# Laptop (listens for THIEF_ALERT, plays alarm)
battery-music relay

# Phone (arms thief catcher, sends THIEF_ALERT on unplug)
battery-music arm --mode relay
```

### Tier 2: Local Socket (USB / Wi-Fi)

For users who hate cloud services or want zero latency. No internet needed.

The client auto-discovers the server through 4 methods, fastest first:

```
[1/4] USB ADB tunnel (127.0.0.1)  -- works even under VPN
[2/4] UDP beacon broadcast         -- Wi-Fi/hotspot auto-discovery
[3/4] Cached last-known-good IP    -- from last_server.json
[4/4] Subnet scan (concurrent)     -- probes all 254 IPs in /24, PING-verified
```

Each candidate is verified with a PING/PONG health check. The server sends ACK confirmations for every START/STOP command.

**USB cable:**
```bash
# Laptop
battery-music serve

# Phone (ADB reverse tunnel is set up automatically)
battery-music client --host 127.0.0.1
```

**Wi-Fi / hotspot:**
```bash
# Laptop
battery-music serve

# Phone (auto-discovers laptop IP)
battery-music client
```

**ADB setup**: Install Android Platform Tools on the laptop. Enable USB Debugging on the phone. Plug in the cable. The script detects the device and sets up the reverse tunnel automatically.

### Tier 3: Telegram Cloud Fallback

For when the worker is down and local network is blocked (e.g., VPN on phone). No extra setup beyond entering a bot token.

1. Message `@BotFather` on Telegram, send `/newbot`, copy the Bot Token
2. Message `@userinfobot`, copy your Chat ID
3. Run `battery-music init` and enter both

The phone updates the bot's description field to "START"/"STOP". The laptop polls the bot's description and executes. No API ID/Hash needed -- a bot can update its own description, and anyone can read it.

This activates automatically when:
- The worker relay is unreachable
- Local socket discovery fails
- The phone has internet access (through proxy or direct)

### Tier 4: Email (SMTP) Alerts

Optional email notifications when battery thresholds are crossed.

1. Google Account -> Security -> enable 2-Step Verification
2. Create an App Password for "Battery Notifier"
3. Enter the 16-character code during `battery-music init`
4. Port 465 = SSL, Port 587 = TLS (auto-detected)

---

## All Commands

| Command | Description |
|---|---|
| `battery-music init` | Run setup wizard (music, thresholds, worker, proxy, notifications) |
| `battery-music init --force` | Reconfigure from scratch |
| `battery-music start` | Auto-detect role: Termux=client, desktop=server |
| `battery-music serve` | Start as server (laptop, local socket mode) |
| `battery-music client` | Start as client (phone, local socket mode) |
| `battery-music client --host 192.168.1.10` | Connect to specific IP |
| `battery-music relay` | Start relay listener (laptop polls worker for alerts) |
| `battery-music arm` | Arm thief catcher (alert on charger unplug) |
| `battery-music arm --mode local` | Thief catcher: alarm plays on this device only |
| `battery-music arm --mode relay` | Thief catcher: alarm goes to worker, laptop plays it |
| `battery-music arm --mode both` | Thief catcher: alarm on both devices (default) |
| `battery-music arm --force` | Arm even if not currently charging |
| `battery-music admin stats` | Show user count, active alerts, bans |
| `battery-music admin ban --user-id N` | Ban a user |
| `battery-music admin broadcast` | Force alert all users (admin test) |
| `battery-music admin clear` | Clear all alerts |
| `battery-music admin login` | Get admin session |
| `battery-music run` | Standalone local monitoring (single device, no network) |
| `battery-music doctor` | Full system diagnostics (9 checks) |
| `battery-music battery` | Print current battery status |

---

## Thief Catcher

Arms the charger monitor. If the charger is unplugged while armed, an alarm fires immediately through all configured channels.

**How it works:**
1. Plug in your charger
2. Run `battery-music arm` (default mode: both local + relay)
3. 3-second grace period (avoids false triggers)
4. If charger is unplugged -> alarm screams on phone + laptop
5. If charger is re-plugged -> alarm stops automatically
6. Press Ctrl+C to disarm

**Modes:**
- `--mode local`: Alarm plays on the phone itself (loud siren)
- `--mode relay`: Alarm goes to worker, laptop picks it up and screams
- `--mode both`: Both at once (default)

**--force flag:** Arms even if not currently charging. Monitors for the plug-to-unplug transition. Useful if you arm before plugging in.

The bundled default alarm is a 2-second siren beep (880/1100Hz alternating). You can set a custom alarm sound during `battery-music init`.

**THIEF_ALERT safety guarantee:** The worker never rate-limits THIEF_ALERT. Even if the user was polling heavily, a thief unplugging the phone will always get through.

---

## Worker Relay (Cloudflare)

### Hosted (for non-technical users)

You deploy the worker on your domain. Users install the app and it works automatically -- the default worker URL is baked into the config. Rate limiting protects your worker from abuse (30 req/min/user). THIEF_ALERT always bypasses rate limiting.

Deploy:
```bash
cd worker/
npx wrangler d1 create battery-relay-db
# Copy database_id into wrangler.toml
npx wrangler d1 execute battery-relay-db --file=schema.sql
npx wrangler secret put ADMIN_KEY
npx wrangler deploy
```

Then edit `battery_notifier/config.py` and set `DEFAULT_WORKER_URL` to your deployed URL.

For obscurity: route through a throwaway domain. The health endpoint at `/` returns a generic "OK" page, not an API description.

### Self-hosted (for paranoid users)

Users deploy their own worker with no rate limiting. Same `worker.js`, different `wrangler.toml`:

```bash
cd worker/self-hosted/
# Edit wrangler.toml: set database_id, change ADMIN_KEY
npx wrangler d1 create battery-relay-db-private
npx wrangler d1 execute battery-relay-db-private --file=../schema.sql
npx wrangler secret put ADMIN_KEY
npx wrangler deploy
```

Then in the app:
```bash
battery-music init
# "Use default hosted worker?" -> answer "n"
# Enter your self-hosted worker URL
```

### Admin Dashboard

Visit `/admin` on your worker URL. Login with your admin key. Shows:
- Total users, active (5min), active alerts, total alerts sent
- Pro users, founding members, banned users
- Recent users table (last 50) with device, platform, battery, alert status
- Ban/unban buttons, broadcast test alert, clear all alerts

Admin CLI commands:
```bash
battery-music admin stats       # User counts
battery-music admin ban --user-id 42
battery-music admin broadcast --alert-type TEST
battery-music admin clear
```

### Worker API

| Endpoint | Method | Auth | Description |
|---|---|---|---|
| `/api/register` | POST | none | Register device, get token |
| `/api/ping` | POST | Bearer | Keep-alive |
| `/api/alert` | POST | Bearer | Send alert (THIEF_ALERT bypasses rate limit) |
| `/api/clear` | POST | Bearer | Clear alert |
| `/api/poll` | GET | Bearer | Check for alerts (laptop polls this) |
| `/admin` | GET | session | HTML dashboard |
| `/admin/login` | POST | none | Get admin session |
| `/admin/stats` | GET | session | JSON stats |
| `/admin/ban` | POST | session | Ban user |
| `/admin/unban` | POST | session | Unban user |
| `/admin/broadcast` | POST | session | Force alert all users |
| `/admin/clear-all` | POST | session | Clear all alerts |
| `/` | GET | none | Health check (returns "OK") |

---

## VPN Detection

The script detects active VPNs by checking for virtual network interfaces:

- **Android/Termux**: scans `/sys/class/net` for `tun*`, `tap*`, `ppp*`
- **Windows**: PowerShell checks for Wintun, TAP, WireGuard, OpenVPN adapters
- **Linux/macOS**: `ip link` / `ifconfig` for tunnel interfaces

When VPN is detected:
- UDP beacon and subnet scan are skipped (VPN blocks them)
- USB ADB tunnel still works (physical wire)
- Cached IP is still tried
- Worker relay still works (just needs internet)
- Telegram fallback still works (through proxy)
- VPN status is printed at startup

---

## Auto-Proxy Detection

If a proxy client (v2rayN, Hiddify, Clash, Nekoray) is running but not configured, the script auto-detects it:

| Port | Protocol | Client |
|---|---|---|
| 12334 | SOCKS5 | Hiddify (Mixed) |
| 10808 | SOCKS5 | v2rayN (SOCKS5) |
| 10809 | HTTP | v2rayN (HTTP) |
| 7890 | HTTP | Clash / Mihomo |
| 2080 | SOCKS5 | Nekoray / Sing-box |
| 1080 | SOCKS5 | Shadowsocks |
| 1081 | SOCKS5 | Alt V2Ray |

Priority: config `proxy_url` > auto-detected > none. All Telegram and worker HTTP requests use the effective proxy automatically.

---

## Smart Server Discovery (Local Socket Mode)

When using `serve`/`client` commands (Tier 2), the client tries 4 methods:

1. **USB ADB tunnel** (127.0.0.1) -- PING verified, works under VPN
2. **UDP beacon** -- server broadcasts on port 8002, client listens
3. **Cached IP** -- last-known-good address saved to `~/.config/battery-music-notifier/last_server.json`
4. **Subnet scan** -- concurrently probes all 254 IPs in /24, each open port PING-verified

Server smart-binds to 0.0.0.0 (all interfaces) first, falls back to 127.0.0.1. Every START/STOP gets an ACK confirmation. PING/PONG health checks prevent false positives during subnet scan.

---

## ACK Protocol

Every command is confirmed:

```
Client -> Server:  "START"
Server -> Client:  "ACK:START"
```

- If no ACK within 5 seconds, client retries
- After 3 consecutive ACK failures, client switches to cloud fallback
- Server answers PING with PONG for health checks

---

## Diagnostics

```bash
battery-music doctor
```

9 checks:
1. Environment (platform, local IP, subnet)
2. VPN status
3. Proxy config + auto-detected proxies
4. Audio assets
5. Battery telemetry
6. Network connectivity (Google, Telegram API)
7. Server reachability (PING test)
8. Worker relay (URL, token, health check)
9. Thief catcher (alarm sound, arm command)

---

## Deployment Scenarios

### Scenario A: Worker relay (recommended, zero config)

On laptop:
```bash
battery-music relay
```
On phone:
```bash
termux-wake-lock
battery-music arm
```

### Scenario B: USB cable (no internet needed)

On laptop:
```bash
battery-music serve
```
On phone:
```bash
battery-music client --host 127.0.0.1
```

### Scenario C: Wi-Fi / hotspot

On laptop:
```bash
battery-music serve
```
On phone:
```bash
battery-music client
```

### Scenario D: Telegram cloud (no worker, no local network)

Setup: run `battery-music init`, enter Telegram bot token + chat ID.

On laptop:
```bash
battery-music serve
```
On phone:
```bash
battery-music client
```

If local discovery fails and internet is available, the client automatically falls back to Telegram. The phone updates the bot description, the laptop polls it.

### Scenario E: Standalone (single device, no network)

```bash
battery-music run
```

Monitors battery and plays sound on the same device. No network, no second device.

---

## Termux Wake Lock

Android kills background apps when the screen turns off. You MUST acquire a wake lock:

```bash
termux-wake-lock
```

Run `termux-wake-release` when done. The `arm` command reminds you if you forget.

---

## Defaults

| Setting | Default | Notes |
|---|---|---|
| min_percentage | 20 | Low battery alert threshold |
| max_percentage | 100 | Full charge alert threshold |
| volume | 0.8 | 0.0 to 1.0 |
| poll_interval | 3.0 | Seconds between battery checks |
| annoying | false | Loop music until conditions normalize |
| quiet_hours | [22, 8] | Do not disturb 22:00 to 08:00 |
| worker_url | hosted worker | Change in init for self-hosted |
| alarm_files | bundled siren | `assets/default_alarm.wav` |
| proxy_url | auto-detected | Scans common ports at startup |

Old defaults (min=99, max=100) caused constant ringing when unplugged near full charge. Fixed to min=20, max=100.

---

## Troubleshooting

- **No alarm sound**: The bundled `default_alarm.wav` should work. If not, run `battery-music init` and set a custom file. On Termux, install `mpv` (`pkg install mpv`).
- **Worker unreachable**: Run `battery-music doctor` to check. If your network blocks it, the auto-proxy detection should route through your local proxy client.
- **Client can't find server (local mode)**: Run `battery-music doctor` on both devices. Check server shows "Listening on 0.0.0.0:8000".
- **VPN blocks discovery**: Use USB cable (`--host 127.0.0.1`) or worker relay. The script tells you when VPN is detected.
- **Telegram fails on Termux**: Android VPN routing issue. Auto-proxy detection should handle it. If not, manually set `proxy_url` in config.
- **Laptop doesn't receive Telegram command**: The Bot Description trick is built-in. A bot cannot read its own messages in a standard chat, so the phone writes to the description and the laptop reads it.
- **Email fails with SSL Error**: Use an App Password, not your Gmail password. Port 465 for SSL, 587 for TLS.
- **Port 8000 is taken**: Use `--port 8001` on both serve and client.
- **Thief catcher false trigger**: The 3-second grace period prevents this. Don't unplug during grace period. Use `--force` if arming before plugging in.

---

## Project Structure

```
battery_notifier/
  __init__.py         Package metadata
  __main__.py         Entry point (python -m battery_notifier)
  cli.py              CLI parser + start/arm/relay/admin commands
  config.py           Config dataclass, proxy sanitizer, defaults
  connection.py        Environment/VPN/proxy detection, discovery, ACK protocol
  remote.py           NotificationServer + RemoteMonitor (local socket mode)
  worker_client.py    HTTP relay client for Cloudflare Worker
  thief_catcher.py    Charger unplug monitor, arm/disarm, alert dispatch
  battery.py          Cross-platform battery reader (psutil + Termux)
  player.py           Audio player (sounddevice -> mpv -> ffplay -> play)
  notifier.py          OS-level notifications (Windows toast, macOS, Linux)
  adb_helper.py       USB ADB bridge auto-setup
  autostart.py        Boot auto-start (Windows VBS / Linux .desktop)
  diagnostics.py      Full system diagnostic scan (9 checks)
  logs.py             Logging setup
  assets/
    default_alarm.wav  Bundled 2-second siren beep
worker/
  worker.js            Cloudflare Worker (D1, auth, rate limit, admin dashboard)
  schema.sql           D1 database schema
  wrangler.toml        Hosted config (rate limiting enabled)
  README.md            Deploy guide for both modes
  self-hosted/
    wrangler.toml      Self-hosted config (rate limiting disabled)
tests/
  test_battery.py      40 tests: PING/PONG, ACK, cache, bind, VPN, proxy, subnet
  test_worker_thief.py 16 tests: worker client, thief catcher, config defaults
```

---

## License

MIT
