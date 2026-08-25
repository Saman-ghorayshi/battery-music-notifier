# LAUNCH RUNBOOK — v2.0.0 ship + go-live

> Execute top to bottom. Every command is copy-paste ready (PowerShell).
> Total time: ~90 min including the GIF recording.

---

## §0 Pre-flight (5 min)

```powershell
# reboot first if you haven't since the WMI wedge incident
Set-Location C:\Users\Samsha\batt\battery-music-notifier
git status --short          # must be EMPTY
python -m pytest -q --timeout=120   # expect: 117 passed (~2.5 min)
```

If anything is dirty or red, STOP and fix before shipping.

---

## §1 Rotate leaked secrets (10 min)

Two secrets appeared in plaintext during development. Both must die:

### 1a. GitHub PAT (`ghp_YOgLCjf…`)
1. https://github.com/settings/tokens → find the token → **Delete**
2. Create replacement: **Generate new token (classic)** or fine-grained;
   scopes needed: `repo` + `workflow` (workflow lets Actions run).
3. Git Credential Manager will store it on first push — nothing to configure.

### 1b. Cloudflare API token (`cfut_…`)
1. https://dash.cloudflare.com/profile/api-tokens → old token → **Roll** or Delete.
2. New token → template **"Edit Cloudflare Workers"**, then edit the token to
   ALSO add **Account › D1 › Edit** (deploys + migrations need it).
3. Save the value somewhere safe for today's deploys; rotate again in 30 days
   as routine hygiene.

### 1c. Relay admin keys (optional but recommended)
- Staging key is `yn5yxf639emldcaq7jhzrk0ov` — rotate via:
  `npx wrangler secret put ADMIN_KEY -c worker/wrangler.staging.toml`
- Prod key lives in `%USERPROFILE%\battery-admin-key.txt` — same command with
  `-c worker/wrangler.toml`.

---

## §2 Push everything to GitHub (5 min)

```powershell
git push -u origin master
```

First push triggers Credential Manager → sign in once in the browser popup.
Verify: `git log origin/master -1` matches local HEAD.

---

## §3 Tag v2.0.0 → CI builds the exe (10 min, mostly waiting)

```powershell
git tag -a v2.0.0 -m "v2.0.0 - public release: two live backends, desktop GUI, security hardening pass"
git push origin v2.0.0
```

Watch it build: https://github.com/Saman-ghorayshi/battery-music-notifier/actions
- `tests` workflow runs the matrix (green expected — it was green locally)
- `release` job builds `dist/battery-music-gui.exe` and opens a **draft Release**

---

## §4 Publish the release (5 min)

1. GitHub → **Releases** → the v2.0.0 draft → edit.
2. Paste this as the body (tweak freely):

```md
## Battery Music Notifier v2.0.0

Cross-platform battery alarm + thief catcher. Phone unplugged? Laptop screams.

- 🖥️ Desktop GUI for Windows (single exe, no install)
- 📱 Android today via Termux one-liner (native app coming)
- ☁️ Two live backends: Cloudflare Worker + self-hosted Node/Postgres
- 🔐 Hashed-only tokens, pairing rotation, rate shields, audit trail
- 🧪 117 unit + 70 live/adversarial tests, CI on 3 OSes × Python 3.9–3.13

> ⚠️ Unsigned binary: Windows SmartScreen will warn. Click *More info* →
> *Run anyway*. Source is fully open — build it yourself if you prefer.
```

3. Untick "Set as draft" → **Publish release**.
4. Verify from a clean spot: download the exe, check Properties → Details shows
   ProductVersion 2.0.0.0, run it.

Optional CLI publish (if `gh` installed & authed):
```powershell
gh release edit v2.0.0 --draft=false
```

---

## §5 Post-release verification (5 min)

```powershell
# fresh clone sanity (proves repo is complete without your machine state)
cd $env:TEMP
git clone https://github.com/Saman-ghorayshi/battery-music-notifier.git bm-verify
cd bm-verify
pip install -e ".[dev]"        # runtime + test deps
python -m pytest -q --timeout=120      # expect 117 passed
```

Delete the clone after. Also confirm the badge of honor:
https://github.com/Saman-ghorayshi/battery-music-notifier/tags shows v2.0.0.

---

## §6 Go live: relay-node public URL on Render (15 min)

Prereq: §2 done (Render builds from GitHub).

1. https://dashboard.render.com → sign up/in → **New +** → **Blueprint**.
2. Select the repo → Render detects `relay-node/render.yaml`.
3. When prompted set env: `ADMIN_KEY=<long random ≥16 chars>`.
   Leave `REDIS_URL` empty (free tier single instance doesn't need it yet).
4. **Apply** → wait for build+deploy (migrations run automatically).
5. Note your URL: `https://battery-relay-xxxx.onrender.com`.

### Smoke test the public URL

```powershell
$U = "https://YOUR-RENDER-URL"
curl.exe -s "$U/health"                       # -> <html>...OK...</html>
curl.exe -s -X POST "$U/api/register" -H "Content-Type: application/json" `
  -d '{\"device_name\":\"render-smoke\",\"platform\":\"win\"}'
# copy the token from the reply into $T, then:
curl.exe -s -X POST "$U/api/alert" -H "Content-Type: application/json" `
  -H "Authorization: Bearer $T" -d '{\"alert_type\":\"THIEF_ALERT\",\"battery_pct\":50,\"is_charging\":false}'
curl.exe -s "$U/api/poll" -H "Authorization: Bearer $T"
```

Expect alert_active=1 then clear works. Then open `$U/admin`, log in with your
ADMIN_KEY, see the dashboard + sparkline.

### Make it official

- README: add under the badges:
  `🌐 Live relay demo: https://your-url.onrender.com (free tier — first hit wakes it)`
- plan.md: tick Phase 6 public-deploy item.

Free-tier notes: service sleeps after ~15 min idle (30 s cold wake);
Postgres free tier expires after 30 days on some plans — set a calendar note
or upgrade to $7/mo instance when you start showing it around.

---

## §7 README hero GIF (40 min)

### Record (pick one)

**A) Xbox Game Bar (simplest):** Win+G → capture the app window while you walk
the shot-list below. Saves to Videos\Captures as .mp4.

**B) OBS (prettier):** display capture at 1920×1080, 30 fps.

### Shot-list (walk it slowly, ~35 s total)

| t | Shot |
|---|---|
| 0–5 s | Dashboard tab: ring ticking, stat cards visible |
| 5–9 s | Thief tab → click ARMED → pulse animation + grace ring |
| 9–15 s | Physically unplug charger → alarm sounds → status flips |
| 15–18 s | Re-plug → stops |
| 18–22 s | Pair tab → Generate → QR appears |
| 22–27 s | Settings tab → drag volume → Save → "Saved." toast |
| 27–32 s | Diagnostics → Run → green cards fill |

(If you can't unplug during recording: use the Termux phone sending a real
THIEF_ALERT, or trigger via `curl` from the register/alert commands above.)

### Convert to optimized GIF

Install ffmpeg once: `winget install Gyan.FFmpeg` (then reopen terminal).

```powershell
# trim dead air first (adjust -ss/-to)
ffmpeg -i input.mp4 -ss 00:00:01 -to 00:00:33 -an demo_raw.mp4

# two-pass palette = crisp colors at small size
ffmpeg -i demo_raw.mp4 -vf "fps=12,scale=900:-1:flags=lanczos,palettegen=stats_mode=diff" palette.png
ffmpeg -i demo_raw.mp4 -i palette.png -lavfi "fps=12,scale=900:-1:flags=lanczos [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=4" demo.gif
```

Target ≤ 8 MB. Too big? drop fps to 10 or scale to 800.

### Embed

```powershell
New-Item -ItemType Directory docs -Force | Out-Null
Move-Item demo.gif docs\demo.gif
```

README.md — directly under the title add:

```md
![Battery Music Notifier demo](docs/demo.gif)
```

Commit:
```powershell
git add docs/demo.gif README.md
git commit -m "readme: hero demo gif"
git push
```

---

## §8 Cleanup after launch (optional, 5 min)

```powershell
# orphan worker on the old CF account (needs THAT account's login/token):
# dash.cloudflare.com (old account) → Workers → battery-relay (late-snow…) → Delete

# local verify clone
Remove-Item -Recurse -Force $env:TEMP\bm-verify
```

---

## Quick reference

| Thing | Value |
|---|---|
| Repo | https://github.com/Saman-ghorayshi/battery-music-notifier |
| Prod relay | https://battery-relay.sthidontknow.workers.dev |
| Staging relay | https://battery-relay-staging.sthidontknow.workers.dev |
| Prod admin key | %USERPROFILE%\battery-admin-key.txt |
| Staging admin key | yn5yxf639emldcaq7jhzrk0ov |
| Actions | /actions · Releases | /releases |
