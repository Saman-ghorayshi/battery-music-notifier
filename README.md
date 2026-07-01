# 🎵 Battery Music Notifier

An advanced, cross-platform distributed network telemetry application. This tool monitors system battery states and coordinates multi-threaded localized alerts, remote SMTP dispatches, and proxy-isolated Telegram webhooks.

Designed with both local simplicity and complex client-server topologies in mind, it allows you to cross-manage device metrics (like your Android phone running Termux and your Windows/macOS/Linux laptop) seamlessly over local networks, wireless hotspots, or offline USB tunnels with zero manual configuration.

---

## 🚀 Advanced Architectural Features

- **Symmetric Client-Server Topology** — Built with fully decoupled, polymorphic runtime endpoints. The application can run entirely on a single machine or split into distributed roles. For example, your Android device (inside Termux) can track local telemetry and trigger high-fidelity playback on your laptop across a local connection.

- **Wireless Auto-Discovery (Zero-Config)** — Employs a lightweight, built-in UDP beacon broadcasting system. When running over a local Wi-Fi router or hotspot, the phone client automatically detects the laptop's IP address in real-time, eliminating the need to manually look up or configure static IP addresses.

- **Non-Blocking Thread Isolation** — Webhooks (Telegram API, SMTP) execute inside isolated background daemon threads. Connection testing and retry logic are decoupled from the main socket listener, preventing system deadlocks during regional network blocks or internet blackouts.

- **Heuristic Network Scanner (`doctor` utility)** — Features a low-level diagnostic suite that sweeps for open inbound port signatures of common desktop proxy cores (such as v2rayN, Hiddify, Clash, Nekoray, Sing-box, and Shadowsocks). It actively tests censorship firewall boundaries and advises on routing profiles.

- **Intelligent Input Normalization** — Employs defensive string sanitization layers to auto-correct imprecise user inputs on the fly. Entries like `socks 10808`, `12334`, or `127.0.0.1:10809` are normalized into valid URI schemas (e.g., `socks5://127.0.0.1:10808`) automatically.

- **Headless Android & Termux Resilience** — Includes dynamic audio fallback pipelines. If standard Python desktop audio libraries (`sounddevice`) are missing on headless systems or mobile architectures, the engine gracefully falls back to native CLI audio players (like `termux-media-player`, `mpv`, or `ffplay`).

- **Automated USB Detection Bridge** — Employs dynamic system path lookup sweeps to locate local Android Debug Bridge (`adb`) tools on Windows, macOS, or Linux, automatically connecting, authorizing, and setting up proxy ports when a mobile device is plugged in over USB.

---

## 🛠️ System Components

| File | Description |
|---|---|
| `battery.py` | Dynamic platform interfaces reading hardware metrics (`psutil`) and mobile terminals (`termux-battery-status`). |
| `remote.py` | High-efficiency TCP socket abstraction handling inter-device commands, UDP wireless auto-discovery beacons, and asynchronous alerting hooks. |
| `adb_helper.py` | Automated background USB bridge search engine and port forwarding controller. |
| `diagnostics.py` | Live validation suite running asset location scans, network telemetry evaluations, proxy sweeps, and censorship bypass checks. |
| `player.py` | Threaded, volume-aware audio loop handling state-safe track interruptions and platform-specific terminal fallbacks. |
| `autostart.py` | Cross-platform boot hook system utilizing VBS wrappers on Windows and XDG autostart schemas on Linux/macOS. |
| `config.py` | Structured TOML parser featuring schema verification and heuristic parameter auto-correction. |
| `cli.py` | Interactive step-by-step setup wizard and unified command-line entry point. |

---

## 📦 Installation & Configuration

### 1. Automated Project Provisioning

Clone your repository and run the automated bootstrap script tailored to your operating system to safely map all pre-compiled dependencies and setup commands:

**🤖 For Linux, macOS, or Android Termux Users**

```bash
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
chmod +x install.sh
./install.sh
```

**💻 For Windows Users (Command Prompt / PowerShell)**

```powershell
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
install.bat
```

### 2. Guided Interactive Setup

Launch the conversational setup wizard to select your notification track via a native file selector, configure battery thresholds, and set up automatic system startup properties:

```bash
battery-music init
```

### 3. Pre-Flight Check (System Doctor)

Run a diagnostic check to verify telemetry, active local ports, connection paths, and Telegram API routing:

```bash
battery-music doctor
```

---

## 📡 Deployment Scenarios

### Scenario A: Standalone Execution (Local Device)

Monitor battery status and trigger audio assets on the host machine:

```bash
battery-music run
```

### Scenario B: Distributed Network (Offline USB Cable Tunnel)

**Setup: Phone Monitors ➔ Laptop Plays Sound**

Ideal when your phone is charging on your desk or a USB port and you want your laptop's speakers to alert you.

On your **Laptop** — run the socket listener server (which automatically attempts to establish an ADB reverse tunnel for you when the phone is plugged in):

```bash
battery-music serve --port 8000
```

On your **Phone** (inside Termux) — start the tracking client targeting your local loopback address:

```bash
battery-music client --host 127.0.0.1 --port 8000
```

### Scenario C: Wireless Hotspot / Wi-Fi Network (Zero-Config)

If your laptop is connected directly to your phone's Wi-Fi hotspot, or they're both on the same home Wi-Fi network, you don't have to look up or type any IP addresses!

**Setup: Phone Monitors ➔ Laptop Plays Sound**

On your **Laptop** — run the server listening on all incoming interfaces:

```bash
battery-music serve --host 0.0.0.0 --port 8000
```

On your **Phone** (inside Termux) — simply start the tracking client without a host IP parameter. It will automatically scan the network, find your laptop, and connect:

```bash
battery-music client --port 8000
```

---

## 🧪 Testing and Verification

To prevent regressions across complex socket lifecycles, threading states, and external API requests, mock-driven unit testing is managed using `pytest-mock`.

Execute your test suite locally:

```bash
pytest -v
```

---

## 📝 License

Distributed under the terms of the MIT License.