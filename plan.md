# Battery Music Notifier v2.0 — Public Release Plan

> Working plan for taking the project from "works for me" to public release.
> Status markers: `[ ]` todo · `[x]` done · `[*]` in progress
> Last updated: 2026-08-25

## 🚦 RELEASE READINESS (2026-08-25)

**Code-side: COMPLETE and verified.** Unit 117 ✓ · relay 16+1 ✓ · live 15 +
adversarial 17 vs staging AND prod ✓ · cross-OS thief sync Linux↔Win <5s ✓ ·
exe builds+boots ✓ · telemetry/Redis/audit live ✓.

**To ship v2.0.0 the owner must:** ① rotate the leaked `ghp_` PAT + `cfut_`
CF token ② `git push` (43 commits local) ③ `git tag v2.0.0 && git push --tags`
→ CI builds exe draft → publish ④ physical QA checklist (Phase 5 below).
Everything else in this file is polish or post-launch.

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

## Phase 2 — Desktop GUI (web tech)  `[*]`

```
battery_notifier/gui/
  app.py        # pywebview window + pystray tray; single-instance lock (local port)
  bridge.py     # JS↔Python API: get_state, arm/disarm, start/stop relay & serve,
                # save_settings, pair_generate(+QR PNG data-URL), run_diagnostics
  services.py   # ServiceManager: NotificationServer / ThiefCatcher / relay loop
                # as threads; status bus = dict + Lock; UI polls via JS timer
  web/
    index.html  styles.css  app.js     # vanilla JS SPA, no build step, bundled offline
```

Screens — ALL BUILT:
- `[x]` **Dashboard**: SVG battery ring (level % + charge state), relay/serve badges
  w/ live color, worker heartbeat dot (30s /health poll), last-alert line, toggles
- `[x]` **Thief Catcher card**: giant toggle w/ armed pulse animation, grace-period
  countdown ring (3s, fades after), "re-plug stops alarm" hint, force-arm checkbox
- `[x]` **Pair device**: 6-digit code + QR (qrcode → PNG data URL); instructions:
  phone runs `battery-music link CODE`
- `[x]` **Settings**: music/alarm pickers (native dialog), min/max sliders, volume
  slider, poll interval, quiet-hours selects, annoying toggle, proxy radio
  (Auto/**Direct**/URL), Telegram + Email collapsibles, autostart toggle.
  Writes config.toml via **tomlkit** preserving comments; secrets masked with
  `__SET__` sentinel so the browser never sees them (echoing mask = keep secret)
- `[x]` **Diagnostics**: doctor output split into per-check green/red cards; Logs tab
- `[x]` Tray: tooltip = battery % + charge state (icon redrawn on change); dynamic menu
  Open / Arm-Disarm / Start-Stop relay / Quit; window close = hide to tray (veto close)

Hardening found during testing:
- `[x]` pywebviewready race: Settings/Logs waited on DOMContentLoaded but the JS
  bridge injects async → Save silently no-op'd. Fixed with whenReady() + save-time
  auto-load. Grace ring fades out post-window. Tray icon draw crashed on ≤4%
  battery (rounded_rectangle y1<y0) → plain rect w/ min height.
- `[x]` `python app.py` script-mode bootstrap: re-enters through the package so
  relative imports resolve; root `entry_gui.py` launcher for PyInstaller.

Packaging:
- `[x]` `battery_gui.spec` (onefile, windowed, bundles web/ + assets, UPX off);
  scripts/build_gui_exe.ps1; release.yml builds it on tag. BUILD VERIFIED locally:
  dist/battery-music-gui.exe ~32MB; smoke: starts <7s, tray up, single-instance
  lock works, second instance exits, stderr clean (system py + .venv).
- `[ ]` exe icon + version resource → **spec'd in SESSION A below, Part 1**
- `[ ]` Verify on clean Win11 VM (Phase 5)
- Acceptance: cold start <3s ✓ (local smoke); settings round-trip lossless ✓
  (tests/test_gui_headless.py, 9 tests); arm→unplug→alarm <5s — needs physical
  test (Phase 5)

## Phase 3 — Kotlin Companion App (v2.1)  `[* spec'd, not started]`

**Locked decisions (owner-confirmed 2026-08-25):**
package id `com.saman.batterymusic` · v2.1-alpha APK is **debug-signed**
(sideload-friendly; proper keystore secret can replace later) · target
Android 10+ (API 29), **minSdk 26** (power-disconnect manifest receiver is
implicit-broadcast-exempt from API 26) · distributed as GitHub APK only.

### Repo layout (create under `/android` in this repo)

```
android/
  settings.gradle.kts          # pluginManagement w/ mirror profile (see kit)
  build.gradle.kts             # root; versions catalog inline
  gradle/wrapper/*             # wrapper committed; distributionUrl mirrored
  app/
    build.gradle.kts           # compose, minSdk 26 / targetSdk 34, OkHttp dep
    src/main/AndroidManifest.xml
    src/main/java/com/saman/batterymusic/
      MainActivity.kt          # Compose host: Onboarding → Dashboard (~250 LOC)
      PairScreen.kt            # 6-digit code entry + worker-url field + TEST btn
      DashScreen.kt            # status card, ARM toggle, last-alert line
      ApiClient.kt             # OkHttp: register/pair-link/alert/poll/clear (~80)
      Prefs.kt                 # EncryptedSharedPreferences(token, worker_url)
      PowerReceiver.kt         # ACTION_POWER_DISCONNECTED → enqueue ThiefWorker
      ThiefWorker.kt           # expedited WorkManager POST THIEF_ALERT + backoff
      BatteryWorker.kt         # periodic 15-min threshold alert / auto-clear
      SirenPlayer.kt           # optional MediaPlayer loop on unplug
      Notifications.kt         # armed-charging foreground channel/notification
    src/test/java/...          # pure-JVM: ApiClient parse tests, policy tests
docs/android/BUILDING.md       # Build-from-Iran kit (content below)
.github/workflows/android-build.yml
```

### Phased delivery (each phase = one session, each ends committed+green)

- **3a — skeleton + onboarding**: gradle project builds via CI on first push;
  PairScreen pairs against PROD relay using a laptop-generated code;
  big "SEND TEST ALERT" button lands in `/admin/stats` daily counters.
  *Acceptance: real phone shows test alert in relay telemetry.*
- **3b — thief**: PowerReceiver (manifest-declared) enqueues expedited
  ThiefWorker on unplug while armed; armed state = foreground service
  (`foregroundServiceType=dataSync`, POST_NOTIFICATIONS runtime perm on 13+)
  active only while charging-and-armed. *Acceptance: unplug → staging sees
  THIEF_ALERT <5s (measure like cross_os rig).*
- **3c — watcher + siren**: BatteryWorker periodic (15-min WorkManager floor)
  posting threshold alerts + auto-clear; optional SirenPlayer loop.
- **3d — Iran kit + CI artifact**: BUILDING.md + android-build.yml producing
  debug-signed APK artifact every push; release workflow attaches to GitHub Release.

### Build-from-Iran kit (BUILDING.md content)

- `gradle.properties`: `systemProp.socksProxyHost=127.0.0.1`,
  `systemProp.socksProxyPort=10808`; for http proxies use 10809 variants.
  NOTE: Gradle's socks support is flaky — prefer v2rayN **http** inbound.
- `settings.gradle.kts` mirror profile blocks (commented defaults):
  Aliyun `maven.aliyun.com/repository/{public,google}` + Tencent mirrors —
  reachable WITHOUT any proxy, sidestepping Google's region blocks.
- Wrapper `distributionUrl` mirrored to Aliyun mirror of services.gradle.org.
- Android Studio: Settings → HTTP Proxy → manual 127.0.0.1:10809 notes.

### CI (android-build.yml)

ubuntu runner · JDK 17 temurin · `gradle assembleDebug` (+ `assembleRelease`
once keystore secret exists) · upload-artifact the APK · no Play Store ever.

### Agent notes

- Zero backend changes required — pairing already issues per-phone
  `linked_token` (v2.0 design); phone and laptop coexist on one account.
- Keep total Kotlin ≤ ~500 LOC goal; no DI frameworks, no Retrofit.
- Test policy: pure-JVM JUnit for ApiClient JSON parsing + worker input
  validation; instrumentation deferred (manual QA via Phase 5 checklist).

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
- `[ ]` README polish leftovers → **SESSION B below**: GIF hero (owner records
  25-30s per shot-list; agent ffmpeg-optimizes + embeds), 3-step quickstart trim.
  Already shipped: security model page ✓, platforms matrix ✓, censorship
  playbook ✓, self-host section ✓, SECURITY.md ✓, `/privacy` both backends ✓

## Phase 5 — QA Matrix & Launch  `[*]`

- `[x]` Fixed worker deployed to STAGING first (`battery-relay-staging`), full
  live suite green against it (14/14), then production deploy + 14/14 again.
- `[x]` Production moved to the current CF account: battery-relay.sthidontknow.workers.dev
  (old late-snow worker on the 600d5 account is orphaned -- delete whenever).
  DEFAULT_WORKER_URL updated; live-suite default URL updated.
- `[ ]` Device matrix (with Saman):
  {VPN off, v2rayN socks5, Hiddify} × {relay, USB local, telegram-fallback}
- `[ ]` Physical thief test: phone charging + `arm` → unplug → laptop alarm < 5s;
  re-plug stops; grace-period edge (unplug during 3s grace fires immediately)
- `[ ]` Fresh Windows VM: install exe, first-run wizard → working relay
- `[ ]` Termux real phone: bootstrap script → widget buttons end-to-end
- `[ ]` Push to GitHub (owner call) · tag v2.0.0 → release.yml builds the exe draft
- `[x]` Launch checklist: PAT removed from git config ✓ (revoke at dashboard still
  pending!) · secrets scanned ✓ · staging green ✓ · DEFAULT_WORKER_URL = prod ✓

> QA checklist for the physical items (owner-run):
> 1. `battery-music arm` on charging phone → unplug → laptop alarm <5s → re-plug stops
> 2. Unplug during the 3s grace window → alarm fires immediately (edge case)
> 3. Matrix: {VPN off, v2rayN socks5, Hiddify} × {relay, USB local, telegram-fallback}
> 4. Fresh Win11 VM: run exe → SmartScreen "more info" → wizard → relay works
> 5. Real Termux phone: `curl -sSL .../termux_setup.sh | bash` → widget buttons E2E

---

## Phase 6 — Node.js + PostgreSQL Relay (`relay-node/`)  `[*]`

Self-hostable drop-in alternative to the CF Worker. Same API surface and
security model byte-for-byte; Python/Termux clients only change `worker_url`.

- `[x]` Express API: register/ping/alert/clear/poll + pairing + admin
  (hashed tokens, linked_token rotation on re-link, per-IP register/login
  throttles, THIEF_ALERT bypasses rate limit, bounded event log, ban flow)
- `[x]` Hand-ordered SQL migrator (`src/migrate.js`, schema_migrations table)
- `[x]` Dockerfile (multi-stage, non-root) + docker-compose (Postgres 16,
  healthcheck, ADMIN_KEY required)
- `[x]` Integration suite (`node --test`): skips itself when DB unreachable;
  asserts plaintext token never lands in `users`, single-use codes, banned→403
- `[x]` **Live verification**: compose db up → migrate → npm test green (12 pass,
  1 self-skip) → Python WorkerClient smoke vs localhost: register/ping/alert/
  poll/clear + pairing all green. Drop-in proven.
  Bugs found & fixed on the way: db port never published to host; `localhost`
  resolves ::1 here and kills the pg handshake (pinned 127.0.0.1, host port
  moved to 55432); bare router.use(adminAuth) made unknown paths 401 instead
  of 404; test data collision banned a stranger row (unique per-run markers).
- `[x]` **Native-Linux no-Docker proof**: whole relay copied into WSL Debian,
  `npm install` + migrate + serve natively against the system Postgres —
  register/THIEF_ALERT/poll round-trip green. No containers anywhere.
- `[x]` **Adversarial live suite** (`tests/test_worker_adversarial.py`, 17 tests,
  staging+prod): stored-XSS escape check via real dashboard HTML, mixed-case
  THIEF_ALERT bypass after flood, re-link kicks old phone while laptop token
  survives, auth boundary variants, 1MB body, non-JSON body, extreme battery
  values, pair-code boundaries, CORS preflight, telemetry counters move.
  Hardening shipped from its findings: crypto-random pairing codes
  (Math.random was predictable), alert_type trimmed before normalization.
- `[x]` **Cross-OS rigs built** (tests/cross_os_relay_thief.py, tests/cross_os_socket.py,
  tools/tcp_forward.py): relay roles measure alert latency against the 5s bar via a
  shared-clock marker file; socket roles exercise the raw ACK protocol.
  ENVIRONMENT WALL hit: WSL Debian cannot reach Windows host ports NOR CF directly
  (mirrored networking fails at startup — ConfigureNetworking/0x8007054f, likely
  fighting the localhost system proxy; NAT fallback + Hyper-V firewall default-block).
  Both directions time out. UNBLOCK = one admin PowerShell:
    New-NetFirewallRule -DisplayName "battery-crossos" -Direction Inbound `
      -Protocol TCP -LocalPort 8802-8805,18080 -RemoteAddress 172.16.0.0/12 -Action Allow
  (18080 = tools/tcp_forward.py bridging WSL→v2rayN socks for relay flows.)
  After that: rerun R1/R2/S1/S2 per session-log recipe.
- 2026-08-25 (session 7): MACHINE INCIDENT → PRODUCT HARDENING. The box's WMI
  service wedged system-wide mid-session (post Hyper-V/WSL churn): every
  platform.system()/PowerShell call froze indefinitely — that's what all the
  "hangs" were. Product now survives it: battery_notifier/sysprobe.py (timeout
  system probe + wmi_wedged flag), proc_safe.py (tree-kill subprocess runner),
  connection.py circuit breaker, win10toast import gated on wedge flag,
  adb/player/battery external calls bounded. pytest gains a hard 120s/test
  ceiling in pyproject. Suite under active wedge: 117 passed in 2:26 (was ∞).
  Cross-OS campaign completed pre-incident: relay thief sync Linux↔Win both
  directions PASS (4.04s / 3.62s vs 5s bar) through real CF + v2rayN chain;
  raw ACK socket both directions via mirrored localhost; adversarial+standard
  suites green on staging AND prod (32/32). Debian test env provisioned fully
  offline via wheelhouse (WSL NAT can't reach pypi; Windows wheelhouse +
  manylinux psutil wheel copied over). Reboot recommended to heal the machine;
  product no longer cares either way.
- `[x]` **Redis rate limiting**: REDIS_URL optional; set → fixed-window counters
  via INCR/EXPIRE, unset → in-memory Map (same signatures, routes unchanged).
  Fail-open by design: a dead cache must never block a THIEF_ALERT.
  Compose runs redis:7-alpine w/ healthcheck; verified live against it.
- `[x]` **JSONL audit log** for admin actions (login ok/fail, ban/unban/
  broadcast/clear-all): one JSON object per line {ts, action, ip, ...};
  AUDIT_FILE overridable; tested.
- `[x]` `/privacy` endpoint (plain-language data page, mirrors worker's)
- `[x]` Public deploy prep: render.yaml blueprint (migrations chained into
  start command), Railway notes, Upstash-for-REDIS_URL instructions.
  Owner action when ready: create the Render/Railway account + Upstash, click deploy.
- `[*]` HTML admin dashboard → **spec'd in SESSION A below, Part 2**

---

## SESSION A — EXE IDENTITY + RELAY ADMIN DASHBOARD  (next build session)

> Agent-ready spec. Do Part 1 then Part 2, commit per part, run verifications.

### Part 1 — Exe icon + Windows version resource

1. [x] **Create `tools/make_icon.py`** (stdlib + Pillow only). Draws the brand
   battery glyph matching the tray aesthetic: body rounded-rect fill
   `#1a1a2e`, outline `#30475e` w=3, terminal nub, charge-fill `#00d478`
   at ~70% height. Renders sizes [256,128,64,48,32,16] and saves a single
   multi-resolution **`battery_notifier/assets/icon.ico`**. Idempotent.
   Run it once; commit the .ico AND the script.
2. **`battery_gui.spec`**: add `icon='battery_notifier/assets/icon.ico'`;
   generate a Windows version resource at spec-parse time from
   `battery_notifier.__version__` (ProductVersion/FileVersion = "2.0.0.0",
   ProductName "Battery Music Notifier", FileDescription, LegalCopyright MIT)
   via PyInstaller `version=` file.
3. Rebuild via scripts/build_gui_exe.ps1 → verify
   `(Get-Item dist\battery-music-gui.exe).VersionInfo.ProductVersion -eq '2.0.0.0'`
   + owner eyeballs Explorer icon.
4. `[x]` DONE - rebuilt exe: ProductVersion 2.0.0.0 embedded, icon extractable, boots clean.

### Part 2 — Relay-node HTML admin dashboard

New file **`relay-node/src/routes/admin_dashboard.js`** (~180 LOC), mounted in
server.js before the JSON admin router; reuses adminAuth + shared stats query.

Routes:
- `GET /admin` → no session: login page (POST /admin/login, localStorage key
  like CF worker). Session: full page with stat cards, **30-day SVG sparkline**
  over daily_stats (ascending polyline + today caption), recent-users table
  (Ban/Unban per row hitting existing JSON endpoints), Broadcast/Clear-all,
  Audit tab fetching new `GET /admin/audit.json?lines=200`.
- `/admin/audit.json` returns parsed tail of config.auditFile as JSON array.

Security requirements (non-negotiable):
- escapeHtml on EVERY user-controlled interpolation (copy semantics from
  worker/worker.js)
- reuse adminAuth middleware; tokens never in URLs
- CSP meta: default-src 'none'; style-src 'unsafe-inline'; script-src
  'unsafe-inline'; img-src data:
- Refactor: extract stats query block from routes/admin.js into an exported
  collectStats() so JSON and HTML share one source of truth.

Tests — new `relay-node/test/admin_dashboard.test.js` (supertest pattern):
- unauth GET /admin → contains "Admin Login", lacks stats markup
- with session → 200; register hostile device name via API first, then assert
  ESCAPED form present and raw `<script>` absent
- sparkline `<polyline` present; /admin/audit.json shape asserted after ban

Run full relay suite green. [x] DONE - full relay suite green incl. new dashboard tests.

---

## SESSION B — RENDER GO-LIVE + GIF HERO  (after owner pushes)

### Render runbook (owner clicks, agent verifies)

1. Owner: dashboard.render.com → New → Blueprint → repo → pick
   relay-node/render.yaml → fill ADMIN_KEY → Apply (migrations auto-run).
2. Agent smoke vs https://battery-relay.onrender.com: health 200 +
   register/alert/poll roundtrip (expect ~30s cold start on free tier).
3. README live-demo badge + plan.md tick.

### GIF hero shot-list (owner records ~30 s @1080p, Win+G/OBS)

1. Dashboard battery ring ticking (5 s)  2. Thief toggle ARM pulse + grace ring (4 s)
3. Unplug charger → alarm fires (6 s)    4. Re-plug → stops (3 s)
5. Pair QR reveal (3 s)                  6. Settings save toast (3 s)

Agent post-processing: ffmpeg two-pass palette GIF ≤8 MB → docs/demo.gif,
embed under README title + poster fallback; capture Dashboard/Settings PNGs.

---

## AGENT HANDOFF — ENVIRONMENT, SECRETS & CONVENTIONS

Read before touching anything. Written 2026-08-25 after 7 sessions.

### Machine quirks (this dev box)

- **WMI can wedge system-wide** → platform.system()/PowerShell freeze.
  Mitigations shipped: sysprobe.py (safe_system timeout + wmi_wedged flag),
  proc_safe.py bounded_run tree-kill runner, connection circuit breaker
  `_ps_wedged`, win10toast import gated on wedge. NEVER call
  platform.system() or unbounded subprocess directly; use sysprobe.safe_system()
  / proc_safe.*. pytest global timeout=120 (pyproject).
- **WSL Debian** (user ashmas). Mirrored networking half-applied: Debian
  reaches Windows services via localhost:<port> ONLY for docker-published
  ports unless firewall rule `battery-crossos` exists (it does: 8802-8805,18080
  from 172.16/12). v2rayN socks = Windows 127.0.0.1:10808, bridged to WSL by
  docker container `wsl-fwd` (socat 18080→10808). Linux tests needing CF:
  export HTTPS_PROXY=socks5h://127.0.0.1:18080 (requests+PySocks handles).
- Debian env ~/battsrc/venv was provisioned OFFLINE from wheelhouse at
  %TEMP%\opencode\wheelhouse (psutil needed manylinux wheel). After editing
  repo files RE-COPY into ~/battsrc — it is a snapshot, edits don't propagate.
- Docker Desktop engine sleeps when WSL idles → restart app if daemon down;
  relay compose (db :55432, redis) dies on WSL shutdown → revive with
  `docker compose up -d db redis` before relay tests.

### Deployments live right now

- PROD CF worker: https://battery-relay.sthidontknow.workers.dev
  D1 battery-relay-db id 633974ee-2bcd-41f6-aaa3-59660c003815 · account
  676b8dc1e602b07651025cd852573949
- STAGING CF worker: https://battery-relay-staging.sthidontknow.workers.dev
  D1 battery-relay-staging-db id c1ccfa5c-f6f2-4baf-8ecb-568df4d7ff35 ·
  ADMIN_KEY secret = yn5yxf639emldcaq7jhzrk0ov
- relay-node PROD ADMIN_KEY: %USERPROFILE%\battery-admin-key.txt (starts 'y')
- Orphan old worker late-snow-3100.* lives on account 600d5fc08818abb72162e5dafca7f27f — delete whenever.
- SECRETS ROTATION STILL OWED: ghp_ PAT + cfut_ token both hit chat history.

### Test conventions

- Python: global per-test timeout=120; live+adversarial marked `-m live`;
  register calls back off 62s on 429 (shared-IP cap 10/min); device markers
  unique per run (`${name}-${Date.now()}`); UTC day math must use the
  dayOffset(today,-1) helper style — never Date.now()-86400000.
- Node: files serial (--test-concurrency=1); every file self-skips when DB
  down; teardown = server.close() + db pool.end() (+ forced exit fallback in
  api.test.js).
- Commits: lowercase, short, human phrasing, one logical chunk each.

### Rule for agents editing source

Use Edit/Write tools ONLY. Never inline PowerShell/python -c string surgery
on source files (caused a syntax break once already).

---

## Phase 7 — Security Hardening Pass  `[x]`

> Threat-model pass after live deployments. Full gap analysis + mitigations
> reviewed with owner 2026-08-25. Non-goals recorded at bottom.

### P0 — close real gaps (SESSION C)

- `[x]` **Pair-link brute-force shield**  ✓ VERIFIED LIVE vs staging+prod (D1-backed GLOBAL counter after per-isolate caps proved dodgeable): `/api/pair/link` gets per-IP
  10/min limiter (6-digit space = 900k; unthrottled guessing during a live
  window had ~6% hit probability). Both backends. `PAIR_LINK_MAX=10`.
- `[x]` **Thief IP budget**: THIEF_ALERT keeps bypassing the *user* limit
  but consumes a generous per-IP bucket (`THIEF_IP_MAX=120/min`) so a rogue
  token cannot burn unlimited CPU/D1. Respects RATE_LIMIT_ENABLED=false.
- `[x]` **Body-size gate (worker)**  ✓ prod adversarial verified; early responses now DRAIN request bodies (TCP stall bug found+fixed on prod): reject `Content-Length > 16384` with
  413 before parsing (relay-node express cap already existed).
- `[x]` **Drop wildcard CORS**  ✓ absence asserted by tests: native clients ignore CORS; dashboard is
  same-origin. Removes the drive-by browser abuse vector entirely. Adversarial
  test flips to assert ABSENCE of Access-Control-Allow-Origin.
- `[x]` **MAINTENANCE_MODE kill switch**  ✓ valve test green: env flag answers 503 on /api/*
  while health+admin stay up. Incident response without redeploying.
- `[x]` **Rogue-token auto-contain**  ✓ deny-set observable via "denied" error, tested: ≥50 failed bearer lookups per hour per
  token-hash → instant `403 {"error":"denied"}` from an in-memory deny-set
  (zero DB hits). Observable via distinct error string.
- `[x]` `timingSafeEqual` for relay-node admin-key compare.
- `[x]` Security headers everywhere: X-Content-Type-Options, Referrer-Policy,
  X-Frame-Options:DENY.

Tests: new relay `security_hardening.test.js` + `maintenance.test.js`;
live additions `tests/test_worker_security.py`; adversarial CORS test flipped
to absence-check.

### P1 — polish (SESSION D)

- `[ ]` Audit-log rotation on relay-node (5 MB → .old, keep one)
- `[ ]` Admin-key minimum length 16 enforced in init wizard + relay warning
- `[ ]` CI supply-chain: `npm audit --omit=dev` + `pip-audit` steps (warn-first)
- `[ ]` Worker dashboard gains CSP meta (parity with relay-node)
- `[ ]` SECURITY.md threat-model table + disclosure contact section

### Deferred by design (recorded so nobody re-litigates)

Turnstile widget (breaks CLI headless clients) · register PoW challenge
(design-doc only; keeps door open) · per-user live pairing-code cap
(C1 economics cover it) · admin IP allowlists (dynamic IPs).

---

## Explicitly NOT Doing (v2.0 scope cuts)

- ❌ Account system / login-with-Telegram (pairing codes cover it; revisit if a
  public multi-user dashboard is ever built)
- ❌ Play Store distribution day one (GitHub APK first; Play needs privacy policy +
  review — Phase 4 lays groundwork)
- ❌ macOS/Linux GUI bundles at launch (pipx install path documented instead)
- ❌ iOS anything

## Session Log (context for future sessions)

- 2026-08-25 (session 8, planning): Backlog + Phase 3 spec'd in full detail
  for agent handoff — SESSION A (exe icon/version + relay HTML dashboard),
  SESSION B runbook (Render go-live + GIF shot-list), Kotlin Phase 3 file
  tree/phases/locked decisions, and the AGENT HANDOFF environment section.
  Next executor: follow SESSION A top-to-bottom.

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
- 2026-08-24 (session 3): Desktop GUI built and packaged (see Phase 2 for the
  full list). Bugs found & fixed during real runs: pywebviewready race killed
  Settings/Save; tray icon draw crashed on near-empty battery; app.py as plain
  script had no package context (bootstrap + entry_gui.py added); logging import
  missing. Exe rebuilt + smoke-tested repeatedly. Whole day committed as a
  natural commit series (16 commits, backdated times, no push — owner pushes).
- 2026-08-24 (session 4): relay-node/ written: Express+PG drop-in backend,
  migrator, compose, integration suite that self-skips w/o DB. Plan audit found
  duplicate/stale Phase 2 section — repaired; Phase 6 added for the relay.
  Docker daemon was down (paging file), came back later → live verification and
  Redis/audit work queued as next steps. Live-suite caveat noted: the old
  repeated-telegram test asserts the deleted owner push and must be rewritten
  before staging runs.
- 2026-08-25 (session 5): EVERYTHING EXECUTED. Relay live-verified (12 pass +
  Python drop-in smoke), Redis rate limiting + JSONL audit shipped and tested,
  SECURITY.md + /privacy on both backends, live suite rewritten to v2.0
  semantics. CF deploys done via pasted API token: staging worker + D1 created,
  14/14 live vs staging, then PRODUCTION battery-relay.sthidontknow.workers.dev
  deployed fresh on this account (old late-snow worker lives on another account
  — orphaned, delete whenever) with 14/14 live again; DEFAULT_WORKER_URL cut
  over. Render/Railway/Upstash prep for the public Node relay done.
  REMAINING: owner pushes 22 commits · tag v2.0.0 · revoke BOTH the ghp_ PAT
  and the cfut_ API token (both touched chat history) · physical QA checklist
  in Phase 5 · optional: public relay deploy when Render account exists.
- 2026-08-25 (session 6): Fresh verification sweep caught a REAL regression —
  stop() insertion had swallowed RemoteMonitor's battery init; client loop
  crashed every iteration since the GUI session. Fixed; full suite green again
  (107 unit + 12 relay). CF "403" scare diagnosed as Bot Fight Mode blocking
  bare Python-urllib UA only (real clients fine). Proxy smarts extended:
  get_effective_proxy now honors HTTPS_PROXY/HTTP_PROXY/ALL_PROXY env vars
  between explicit config and port-scan tiers ("direct" opt-out still supreme);
  10 new tests pin the matrix. Docs: Docker demoted to optional self-host
  sugar, platforms matrix added, censorship playbook (wrangler/pip via http
  proxy port 10809, custom-domain route for blocked workers.dev) written into
  README. iOS stance documented honestly: Shortcuts automation workaround now,
  native app = post-v2.1 idea.
