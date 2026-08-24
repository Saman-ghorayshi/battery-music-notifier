# Battery Music Notifier v2.0 — Public Release Plan

> Working plan for taking the project from "works for me" to public release.
> Status markers: `[ ]` todo · `[x]` done · `[*]` in progress
> Last updated: 2026-08-24

---

## Locked Decisions

| Decision | Choice |
|---|---|
| Version | **v2.0.0** |
| GUI | **Web-tech look** (pywebview + vanilla JS SPA), pystray tray icon |
| Desktop packaging | **Windows-first `.exe`** (PyInstaller); mac/Linux via `pipx` at launch |
| Worker-side global Telegram push | **DELETE** (owner-chat spam + username leak at scale) |
| Accounts system | **NO** — anonymous device tokens + 6-digit pairing stays |
| Phone strategy v2.0 | **Termux** one-liner installer + Termux:Widget home-screen buttons |
| Phone strategy v2.1 | **Native Kotlin app**, distributed as **GitHub APK** (no Play Store day one) |
| Backend changes needed for Kotlin | **ZERO** — worker endpoints already support everything |

---

## Findings That Motivated This Plan (verified by real tests, Aug 2026)

### What works (tested green)
- Unit suites: 98/98 pass (test_battery 40, test_bugfixes 42, test_worker_thief 16)
- Live TCP socket protocol: PING/PONG, ACK:START/STOP/THIEF_ALERT/THIEF_STOP,
  shared-secret auth rejects intruders (`ERR:UNAUTHORIZED`), player starts/stops — 6/6
- UDP beacon discovery + smart_find_server + host cache — pass
- `relay` CLI ↔ mock Cloudflare worker full pipeline (register→poll→alarm→clear) — 9/9
- **LIVE production end-to-end** vs deployed CF Worker + D1: register, token persist,
  alert delivered, alarm triggered, cleared — 7/7
- Live worker safe subset (11 tests): health, register, ping, bad-token 401,
  battery alert+poll, clear, pairing flow incl. single-use/expired/non-numeric — 11/11
- `doctor` / `battery` CLI — pass

### Blockers / bugs found
| ID | Sev | Finding | Where |
|---|---|---|---|
| P1 | 🔴 | GitHub PAT embedded in git remote URL (never committed; revoke + re-point) | `.git/config` |
| W1 | 🔴 | schema.sql column `banned` but code queries `is_banned` → fresh deploys crash | `worker/schema.sql` |
| W2 | 🔴 | User auth tokens stored plaintext in D1 | `worker/worker.js` register/authUser |
| W3 | 🔴 | Every user's alert sends Telegram msg to OWNER chat w/ device name (spam+leak) | `worker.js:173-210` |
| W4 | 🟠 | No rate limit on `/api/register` → D1 row spam once URL is public | `worker.js` |
| W5 | 🟠 | XSS: `device_name` interpolated unescaped into admin dashboard HTML | `dashboardHTML()` |
| C1 | 🟠 | Corrupted config.toml crashed EVERY command with raw traceback (fixed: graceful fallback) | `config.py Config.load` |
| C2 | 🟡 | `quiet_hours = [23,7]` silently ignored — `_resolve_annotation` missed lowercase `list[int]` (fixed) | `config.py` |
| C3 | 🟡 | `worker_url=""` in user config killed relay mode (fixed locally; wizard should prevent) | `cli.py init`, config.toml |
| C4 | 🟡 | adb installed + no phone ⇒ serve/start stalls ~6s before listening | `remote.py run()` |
| C5 | 🟡 | Proxy auto-detect hijacks traffic; no way to force direct | `connection.get_effective_proxy` |
| C6 | 🟡 | Version chaos: pyproject 1.0.0 / cli --version hardcoded / __init__ 1.2.0 | 3 files |
| C7 | 🟢 | Test suite slow (~8 min): every object construction runs PowerShell VPN detect | perf note only |

---

## Phase 0 — Security & Correctness Blockers  `[x]`

1. `[x]` **PAT**: DONE 2026-08-24 — root cause was an `insteadOf` rewrite in the
   *global* `~/.gitconfig` injecting the PAT into every GitHub URL (repo remote
   itself was clean). Section removed; remote verified clean.
   ⚠️ OWNER ACTION STILL OPEN: revoke `ghp_YOgL...` at GitHub → Settings →
   Developer settings (it sat in world-readable global config).
   Auth now goes through Git Credential Manager.
2. `[x]` **Secret hygiene**: `.pre-commit-config.yaml` added (gitleaks v8 + hygiene hooks);
   `.gitignore` extended: `.wrangler/`, `.dev.vars`, `last_server.json`, `*.log`,
   `config.toml.bak`, `.env`; typos (`*.wrangler/`, `*node_modules/`) cleaned.
3. `[x]` **schema.sql**: aligned 1:1 with worker.js. Extra drift found & fixed beyond
   `banned`: `id`→`user_id`, missing `total_alerts`, missing `events` table entirely,
   `admin_sessions.created_at` used but undefined. Added `linked_token`,
   pairing-by-`user_id`, new indexes. `worker/migration_v2.sql` ships as one-shot;
   migration section added to `worker/README.md`.
4. `[x]` **Hash user tokens** (sha256 hex): register stores hash, plaintext returned once;
   authUser hashes Bearer then matches `token OR linked_token`.
   Pairing redesigned: codes carry `user_id` only; link mints a fresh linked token
   (hashed at rest), rotates on re-link (old phone de-auths). Laptop's primary token
   never invalidated by pairing. Safe cutover via auto-re-register on 401 confirmed.
5. `[x]` **Global Telegram push block deleted** from handleSendAlert. Worker is now a
   pure relay; per-user channels live client-side (notifier.py).
6. `[x]` **Register throttle**: 10 reg/min/IP via shared rateBuckets (`reg:<ip>`),
   honors RATE_LIMIT_ENABLED for self-hosters.
7. `[x]` **Admin hardening**: escapeHtml() applied to device_name/platform/alert_type/
   user_id in dashboard rows + data-uid; failed-login throttle 5/min/IP (`alogin:<ip>`),
   reset on success.
8. `[x]` **Version unify → 2.0.0**: single source `battery_notifier/__init__.py`;
   pyproject uses `dynamic = ["version"]` (setuptools attr); cli imports `__version__`.
9. `[x]` **Non-blocking ADB**: `_start_adb_bridge_async()` daemon-thread helper in
   remote.py; both RemoteMonitor.run (forward) and NotificationServer.run (reverse)
   start their loops immediately (fixes C4).
10. `[x]` **Proxy opt-out** (fixes C5): `sanitize_proxy_url("direct"/"off"/"none") → "direct"`;
    `get_effective_proxy` returns None and skips detect/port-scan; notifier.py guards
    against passing the literal keyword as a proxy URL; wizard offers Direct option.

## Phase 1 — VPN-Proof By Default  `[x]`

- `[x]` Init wizard restructured: relay is the FIRST connectivity question,
  framed as the default VPN-proof path; proxy + local-socket moved under
  "[Advanced]" sections at the end.
- `[x]` VPN keywords broadened — Windows PS regex + ipconfig fallback now cover
  Cloudflare WARP, Tailscale, Mullvad, NordLynx/NordVPN, Proton, ExpressVPN,
  ZenMate; Unix adds utun*/wg*/tailscale* prefixes; Android already iface-based.
- `[x]` `doctor` gains "[10] Connection Tier Verdict": Relay OK/unreachable,
  Telegram ready/blocked, USB adb-present?, Wi-Fi discovery blocked-by-VPN/available.
  Also fixed doctor flagging `proxy_url="direct"` as MALFORMED.
- `[x]` README support matrix: tier × {no VPN, client VPN, censored net w/ proxy}
  inserted above "Connection Tiers", plus direct-opt-out + doctor pointers.

## Phase 2 — Desktop GUI (web tech)  `[ ]`

> NEXT UP. Not started this session — see structure below.

## Phase 2 — Desktop GUI (web tech)  `[ ]`

```
battery_notifier/gui/
  app.py        # pywebview window + pystray tray; single-instance lock (local port)
  bridge.py     # JS↔Python API: get_state, arm/disarm, start/stop relay & serve,
                # save_settings, pair_generate(+QR PNG data-URL), run_diagnostics
  services.py   # ServiceManager: NotificationServer / ThiefCatcher / relay loop
                # as threads (pattern proven in integration tests); status bus
                # = dict + Lock; UI polls via JS timer (simplest, no push needed)
  web/
    index.html  styles.css  app.js     # vanilla JS SPA, no build step, bundled offline
```

Screens:
- `[ ]` **Dashboard**: SVG battery ring (level % + charge state), connection-tier
  badge (Relay/USB/Wi-Fi/Telegram) w/ live color, worker heartbeat dot, last-alert line
- `[ ]` **Thief Catcher card**: giant toggle, grace-period countdown ring, armed pulse
  animation, "re-plug stops alarm" hint
- `[ ]` **Pair device**: show 6-digit code + QR (`qrcode` lib → data URL);
  instructions: phone runs `battery-music link CODE`
- `[ ]` **Settings**: music/alarm pickers (native file dialog), min/max sliders,
  volume slider, poll interval, quiet-hours selects, annoying toggle,
  proxy radio (Auto/**Direct**/URL), Telegram + Email collapsibles, autostart toggle
  (wires to `autostart.py`). Writes config.toml via **tomlkit** to preserve comments
- `[ ]` **Diagnostics**: doctor's 9 checks as async green/red cards; Logs tab
- Tray: tooltip = battery %; menu Open / Arm-Disarm / Start-Stop relay / Quit
- Deps: `pywebview`, `pystray`, `Pillow`, `qrcode`; dev: `pyinstaller`, `tomlkit`
- `[ ]` Packaging: PyInstaller onefile `--windowed`, bundle assets + web/, icon,
  version resource; verify on clean Win11 VM; document SmartScreen unsigned warning
- Acceptance: cold start < 3s; arm→unplug→alarm < 5s; settings round-trip lossless

## Phase 3 — Kotlin Companion App (v2.1, post-launch)  `[ ]`

Repo layout `/android`. Compose UI, minSdk 26, ~500 LOC goal. Zero backend changes.

- `[ ]` **Thief catcher**: manifest receiver on `ACTION_POWER_DISCONNECTED`
  (implicit-broadcast exempt since API 26 — Android wakes app even if closed)
  → expedited WorkManager job POSTs `THIEF_ALERT` w/ stored token.
  Foreground service only while armed-charging (listens BATTERY_CHANGED).
- `[ ]` **Battery watcher**: WorkManager periodic (~15 min floor) posts
  `/api/alert` when threshold crossed, `/api/clear` on normalize.
- `[ ]` **Onboarding**: enter 6-digit pair code → `/api/pair/link` → token into
  EncryptedSharedPreferences; default worker URL baked; "Send TEST alert" button.
- `[ ]` **Local siren option**: MediaPlayer loop on unplug (mode=local equivalent).
- `[ ]` **Build-from-Iran kit** (docs/android/BUILDING.md):
  - gradle.properties: `systemProp.socksProxyHost=127.0.0.1`,
    `systemProp.socksProxyPort=10808`, http/https variants via 10809 (v2rayN)
  - settings.gradle mirror profile: Aliyun/Tencent Maven mirrors
    (reachable WITHOUT proxy — sidesteps Google's region blocks entirely)
  - mirrored `distributionUrl` for Gradle wrapper
  - Android Studio: Settings → HTTP Proxy notes
- `[ ]` **CI builds APK** (GitHub runners are not sanctioned): release workflow
  assembles + signs (keystore as repo secret), attaches to GitHub Release.
  Local builds optional, never required for releases.

## Phase 4 — CI/CD, Termux One-Click, Docs  `[*]`

- `[x]` `.github/workflows/test.yml`: pytest matrix 3.9–3.13 × {ubuntu, windows},
  unit only (`-m "not live"`; live tests also excluded by default via pyproject
  addopts + module-level `pytestmark = pytest.mark.live` in test_worker_live.py)
- `[x]` `.github/workflows/gitleaks.yml` (push/PR/daily cron) + pre-commit hook
- `[x]` `.github/workflows/release.yml`: tag → PyInstaller onefile exe → draft
  GitHub Release with artifact + smoke test (`--version`). Revisit after GUI:
  add icon/version-resource/windowed flag and web/ assets.
- `[x]` Termux: `termux/termux_setup.sh` (pkg deps + pip install from repo,
  non-interactive default config, wake-lock hints, widget shortcut install);
  hosted via `curl -sSL ... | bash`
- `[x]` `termux/shortcuts/`: "Start Monitor" + "Arm Thief" Termux:Widget scripts
  (wake-lock acquired automatically in both)
- `[ ]` README rewrite: GUI GIF hero, 3-step quickstart, security model page,
  VPN matrix done ✓ but full rewrite pending GUI; SECURITY.md; `/privacy`
  page on worker

## Phase 5 — QA Matrix & Launch  `[ ]`

> Requires deployed staging worker + physical devices (with Saman). Unstarted.
> Launch checklist reminder: PAT revoke still pending on owner (P0.1).

- `[ ]` Deploy fixed worker to STAGING subdomain first; run full live suite vs it;
  modest load test (register/poll burst ≤ CF limits); then production deploy
- `[ ]` Device matrix (with Saman):
  {VPN off, v2rayN socks5, Hiddify} × {relay, USB local, telegram-fallback}
- `[ ]` Physical thief test: phone charging + `arm` → unplug → laptop alarm < 5s;
  re-plug stops; grace-period edge (unplug during 3s grace fires immediately)
- `[ ]` Fresh Windows VM: install exe, first-run wizard → working relay
- `[ ]` Termux real phone: bootstrap script → widget buttons end-to-end
- `[ ]` Launch checklist: PAT rotated ✓ · secrets scanned ✓ · staging green ✓ ·
  DEFAULT_WORKER_URL points at production ✓ · tag v2.0.0 ✓

---

## Explicitly NOT Doing (v2.0 scope cuts)

- ❌ Account system / login-with-Telegram (pairing codes cover it; revisit if a
  public multi-user dashboard is ever built)
- ❌ Play Store distribution day one (GitHub APK first; Play needs privacy policy +
  review — Phase 4 lays groundwork)
- ❌ macOS/Linux GUI bundles at launch (pipx install path documented instead)
- ❌ iOS anything

## Session Log (context for future sessions)

- 2026-08-24: Full audit + real-device-free integration testing done (see Findings).
  Fixed live: config.toml repaired (backup at config.toml.bak), graceful TOML
  fallback added (C1), quiet_hours annotation bug fixed (C2), worker_url restored
  in user config (C3). Live E2E vs production worker verified 7/7.
  Integration harnesses live in `%TEMP%\opencode\battint\` (integ_socket2.py,
  integ_relay.py, integ_live.py) — reusable smoke tests.
- 2026-08-24 (session 2): Phase 0 + Phase 1 COMPLETE, Phase 4 mostly complete.
  PAT root-caused to global `insteadOf` in ~/.gitconfig (not repo remote) and
  removed; owner must still REVOKE the token at github.com. worker.js: token
  hashing + linked_token pairing redesign, register/login IP throttles, dashboard
  XSS escape, TG push block deleted, router cleanup. schema.sql rewritten to match
  every query (id→user_id, total_alerts, events table, linked_token, pairing by
  user_id) + worker/migration_v2.sql. remote.py ADB bridge now async (C4).
  Proxy "direct" opt-out end-to-end incl. notifier guard (C5). Version unified
  2.0.0 via pyproject dynamic attr. Init wizard relay-first with Advanced section.
  VPN keywords broadened; doctor tier verdicts ([10]); README support matrix.
  CI: test.yml (3.9–3.13 × ubuntu/windows), gitleaks.yml, release.yml skeleton;
  live tests quarantined behind `pytest.mark.live` (deselected by default);
  termux/ installer + widget shortcuts added. Unit suite verified: 98/98 pass,
  15 live deselected. NEXT: Phase 2 GUI (gui/app.py, bridge.py, services.py,
  web/ SPA), then README rewrite + SECURITY.md + /privacy, then Phase 5 QA.
