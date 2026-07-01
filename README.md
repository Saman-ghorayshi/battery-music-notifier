***

# 🎵 Battery Music Notifier

An advanced, cross-platform distributed network telemetry application. This tool monitors system battery states and coordinates multi-threaded localized alerts, remote SMTP dispatches, and proxy-isolated Telegram webhooks.

Designed with both local simplicity and complex client-server topologies in mind, it allows you to cross-manage device metrics (like your Android phone running Termux and your Windows/macOS/Linux laptop) seamlessly over local networks, wireless hotspots, offline USB tunnels, or even completely isolated VPNs using the Telegram Cloud fallback.

---

## 🚀 Advanced Architectural Features

- **Symmetric Client-Server Topology** — Fully decoupled runtime endpoints. Run entirely on one machine, or split roles: your Android device (Termux) tracks telemetry and triggers high-fidelity playback on your laptop.
- **Wireless Auto-Discovery (Zero-Config)** — Built-in UDP beacon broadcasting. The phone client automatically detects the laptop's IP on port 8002 over Wi-Fi/Hotspot, eliminating manual IP configuration.
- **Telegram Cloud Fallback (Bot Description Trick)** — If local networks are blocked by Android VPNs or firewalls, the client seamlessly falls back to Telegram. Using a single Bot, the phone updates the Bot's description to "START/STOP", which the laptop polls and executes instantly. No API ID/Hash or dual bots required!
- **Non-Blocking Thread Isolation** — Webhooks (Telegram API, SMTP) execute in isolated daemon threads, preventing deadlocks during network blocks.
- **Heuristic Network Scanner (`doctor` utility)** — Sweeps for inbound ports of common proxy cores (v2rayN, Hiddify, Clash, Nekoray) and actively tests censorship firewall boundaries.
- **Intelligent Input Normalization** — Auto-corrects imprecise user proxy inputs (e.g., `socks 10808`, `12334`) into valid URI schemas (`socks5://127.0.0.1:10808`).
- **Headless Android & Termux Resilience** — Dynamic audio fallback pipelines. Falls back to `termux-media-player`, `mpv`, or `ffplay` if desktop audio libraries are missing.
- **Automated USB Detection Bridge** — Dynamic `adb` path lookup and automatic reverse port tunneling for USB connections.

---

## 📦 Installation

### 🤖 Android (Termux) Setup
Termux requires specific packages to handle battery telemetry, audio playback, and background execution.

```bash
# 1. Install required Termux packages
pkg update && pkg upgrade -y
pkg install python termux-api mpv git -y

# 2. Ensure the Termux:API app is installed from Google Play / F-Droid
# (termux-battery-status will fail without it)

# 3. Clone and install
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
pip install -e .
```

### 💻 Windows / macOS / Linux Setup

```bash
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
pip install -e .
```

---

## ⚙️ Guided Interactive Setup

Launch the setup wizard to select your music, set battery thresholds, and configure proxy/notifications:

```bash
battery-music init
```

*Tip: If you need to reconfigure later, run `battery-music init --force`.*

### Setting up Email Notifications (SMTP)
To send email alerts, the script requires an **App Password** (not your regular email password) due to modern security standards:
1. Go to your Google Account -> **Security**.
2. Enable **2-Step Verification**.
3. Search for **App Passwords** and create one for "Battery Notifier".
4. When the wizard asks for `email_password`, enter the 16-character code.
5. Use `smtp.gmail.com` and port `587` (TLS) or `465` (SSL). The app auto-detects the encryption!

### Setting up Telegram Notifications (Cloud Fallback)
1. Open Telegram and message `@BotFather`.
2. Send `/newbot` and follow prompts to create your bot.
3. Copy the **Bot Token**.
4. Message `@userinfobot` to get your **Chat ID**.
5. Enter these into the wizard when prompted. The laptop will now automatically poll this bot for commands!

---

## 📡 Deployment Scenarios

### Scenario A: Standalone Execution (Local Device)
Monitor battery and play music on the host machine:
```bash
battery-music run
```

### Scenario B: Distributed Network (Offline USB Cable)
*Phone monitors ➔ Laptop plays sound via USB cable.*

On **Laptop**:
```bash
battery-music serve --port 8000
```
On **Phone (Termux)**:
```bash
battery-music client --host 127.0.0.1 --port 8000
```

### Scenario C: Wireless Hotspot / Wi-Fi (Zero-Config)
*Phone monitors ➔ Laptop plays sound over Wi-Fi.*

On **Laptop**:
```bash
battery-music serve --host 0.0.0.0 --port 8000
```
On **Phone (Termux)**:
```bash
battery-music client --port 8000
# (Host defaults to "auto", triggering UDP Wi-Fi discovery)
```

---

## ⚠️ Crucial Termux (Android) Requirement: Wake Lock

Android aggressively kills background apps when the screen turns off to save battery. If you run the `client` in Termux and lock your phone, **the music will stop and alerts will fail**.

**You MUST acquire a wake lock before starting the client:**

```bash
termux-wake-lock
```
*You will see a persistent notification showing that Termux is awake in the background. Run `termux-wake-release` to disable it when done.*

---

## 🩺 Diagnostics & Testing

### Pre-Flight Check (System Doctor)
Verify hardware telemetry, audio assets, proxy configurations, and Telegram API routing:
```bash
battery-music doctor
```

### Unit Tests
The project includes mock-driven tests using `pytest-mock` to verify socket lifecycles, threading, and API requests.

```bash
pytest -v
```

---

## 🧩 Troubleshooting

- **Music doesn't play on Termux:** Ensure `mpv` is installed (`pkg install mpv`) and you have granted Termux storage access (`termux-setup-storage`).
- **Telegram fails on Termux but works on Laptop:** Your Android VPN is routing traffic poorly. The script will automatically attempt the Telegram Cloud Fallback, but ensure your `proxy_url` in Termux is correctly set to bypass local VPN restrictions (e.g., `socks5://127.0.0.1:10808`).
- **Laptop doesn't receive Telegram command:** Make sure you are using the **Bot Description trick** (built-in automatically). A bot cannot read its own messages in a standard chat, so the phone updates the bot's description, which the laptop reads.
- **Email fails with SSL Error:** Ensure you are using an **App Password**, not your standard Gmail password. Verify port `465` is used for SSL, or `587` for TLS (the wizard handles this automatically).

---

## 📝 License

Distributed under the terms of the MIT License.