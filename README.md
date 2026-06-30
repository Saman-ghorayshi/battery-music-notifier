# 🎵 Battery Music Notifier

An enterprise-grade, cross-platform distributed network telemetry application. This tool monitors system battery states and coordinates multi-threaded localized alerts, remote SMTP dispatches, and proxy-isolated Telegram webhooks.

Designed with both local simplicity and complex client-server topologies in mind, it allows you to cross-manage device metrics (like your Android phone running Termux and your Windows/macOS/Linux laptop) seamlessly over local networks or offline USB tunnels.

## 🚀 Advanced Architectural Features

- **Symmetric Client-Server Topology**: Built with fully decoupled, polymorphic runtime endpoints. The application can run entirely on a single machine or split into distributed roles. For example, your Android device (inside Termux) can track local telemetry and trigger high-fidelity playback on your laptop across an offline USB tunnel via ADB port proxy links.
- **Non-Blocking Thread Isolation**: Webhooks (Telegram API, SMTP) execute inside isolated background daemon threads. Connection testing and retry logic are decoupled from the main socket listener, preventing system deadlocks during regional network blocks or internet blackouts.
- **Heuristic Network Scanner (`doctor` utility)**: Features a low-level diagnostic suite that sweeps for open inbound port signatures of common desktop proxy cores (such as v2rayN, Hiddify, Clash, Nekoray, Sing-box, and Shadowsocks). It actively tests censorship firewall boundaries and advises on routing profiles.
- **Intelligent Input Normalization**: Employs defensive string sanitization layers to auto-correct imprecise user inputs on the fly. Entries like `socks 10808`, `12334`, or `127.0.0.1:10809` are normalized into valid URI schemas (e.g., `socks5://127.0.0.1:10808`) automatically.
- **Headless Android & Termux Resilience**: Includes dynamic audio fallback pipelines. If standard python desktop audio libraries (`sounddevice`) are missing on headless systems or mobile architectures, the engine gracefully falls back to native CLI audio players (like `termux-media-player`, `mpv`, or `ffplay`).

## 🛠️ System Components

| File | Description |
|---|---|
| `battery.py` | Dynamic platform interfaces reading hardware metrics (`psutil`) and mobile terminals (`termux-battery-status`). |
| `remote.py` | High-efficiency TCP socket abstraction handling inter-device commands, offline signals, and asynchronous alerting hooks. |
| `diagnostics.py` | Live validation suite running asset location scans, network telemetry evaluations, proxy sweeps, and censorship bypass checks. |
| `player.py` | Threaded, volume-aware audio loop handling state-safe track interruptions and platform-specific terminal fallbacks. |
| `autostart.py` | Cross-platform boot hook system utilizing VBS wrappers on Windows and XDG autostart schemas on Linux/macOS. |
| `config.py` | Structured TOML parser featuring schema verification and heuristic parameter auto-correction. |
| `cli.py` | Interactive step-by-step setup wizard and unified command-line entry point. |

## 📦 Installation & Configuration

### 1. Project Provisioning

Clone your custom repository and install the module locally in editable mode along with development dependencies:

For Linux, macOS, or Android Termux Users
```bash
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
chmod +x install.sh
./install.sh
pip install -e ".[dev]"
```
For Windows Users (Command Prompt / PowerShell)
```bash
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git
cd battery-music-notifier
install.bat

pip install -e ".[dev]"
```
Launch the conversational setup wizard to select your notification track via a native file selector, configure battery thresholds, and set up automatic system startup properties:

```bash
battery-music init
```

### 3. Pre-Flight Check (System Doctor)

Run a diagnostic check to verify telemetry, active local ports, connection paths, and Telegram API routing:

```bash
battery-music doctor
```

## 📡 Deployment Scenarios

### Scenario A: Standalone Execution (Local Device)

Monitor battery status and trigger audio assets on the host machine:

```bash
battery-music run
```

### Scenario B: Distributed Network (Offline USB Cable Tunnel)

#### Setup 1: Phone Monitors ➔ Laptop Plays Sound

Ideal when your phone is charging on your desk or a USB port and you want your laptop's speakers to alert you:

**On your Laptop:** Run the socket listener server:

```bash
battery-music serve --port 8000
```

**On your Laptop:** Establish an ADB reverse tunnel to route local phone signals up the USB charging cable:

```bash
adb reverse tcp:8000 tcp:8000
```

**On your Phone (inside Termux):** Start the tracking client:

```bash
battery-music client --host 127.0.0.1 --port 8000
```

#### Setup 2: Laptop Monitors ➔ Phone Plays Sound (The Reverse!)

Ideal when your laptop is plugged in across the room and you want your phone in your pocket to ring:

**On your Phone (inside Termux):** Run the socket listener server:

```bash
battery-music serve --port 8000
```

**On your Laptop:** Establish an ADB forward tunnel to route outbound laptop signals down the USB charging cable:

```bash
adb forward tcp:8000 tcp:8000
```

**On your Laptop:** Start the tracking client:

```bash
battery-music client --host 127.0.0.1 --port 8000
```

## 🧪 Testing and Verification

To prevent regressions across complex socket lifecycles, threading states, and external API requests, mock-driven unit testing is managed using `pytest-mock`.

Execute your test suite locally:

```bash
pytest -v
```

## 📝 License

Distributed under the terms of the MIT License.