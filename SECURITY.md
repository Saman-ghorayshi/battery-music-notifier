# Security Model

Short version: the server stores enough to wake you up when your battery is
low or someone steals your phone, and nothing more.

## What gets stored

| Data | Where | Why |
|---|---|---|
| sha256 hash of your device token | users table | so requests authenticate |
| sha256 hash of a paired phone's token | users.linked_token | same, for the second device |
| device name + platform string | users table | shown to you in the admin dashboard |
| battery %, charging flag, alert type/timestamps | users table | the whole point of the app |
| last 200 alert events per user | events table | debugging history |
| aggregate daily counters (registrations, alerts, active devices) | daily_stats table | operator dashboard trends. Counts of events only -- there is no way to tie a row back to a person, and old days freeze permanently |

No emails, no phone numbers, no accounts, no location, no analytics.
Pairing codes hold a user id and expire after 5 minutes.

## Tokens

- Tokens are 24 random bytes (Web Crypto / node crypto), hex-encoded.
- The database only ever sees `sha256(token)`. The plaintext is shown once,
  at registration or pair-link, and lives in your local config file
  (`~/.config/battery-music-notifier/config.toml`). Guard that file.
- A leaked database therefore does not leak usable credentials.
- Pairing mints a *separate* linked token for the phone. Re-linking rotates
  it, which kicks out the previously paired device.

## Abuse controls

- Bearer auth on every API route except register and pair-link.
- Rate limits: 30 req/min per user; registrations capped at 10/min/IP;
  failed admin logins at 5/min/IP.
  `THIEF_ALERT` bypasses rate limits by design -- safety alerts must never
  be blocked. On the Node backend this path fails open if Redis dies.
- Admin sessions are hashed, expire after 1 hour.
- Admin dashboard HTML-escapes every user-controlled field (device names come
  from unauthenticated registration -- they are attacker-writable).
- Banned devices get an explicit 403 `banned`, not a generic 401.

## What the server will never do

- Send notifications anywhere on its own. Delivery (desktop sound, Telegram,
  email) happens client-side with credentials from your local config. There
  is no owner/admin push channel reading your alerts -- that was removed in
  v2.0 on purpose.

## Self-hosting

Both backends are self-hostable:

- Cloudflare Worker: see `worker/README.md` (D1, free tier)
- Node.js + PostgreSQL (+ optional Redis): see `relay-node/README.md`

Self-hosting gives you full control of the data above.

## Reporting

Found something? Open a private security advisory via GitHub
(Security -> Advisories) instead of a public issue.

## Threat model (v2.0 hardening pass)

| Threat | Mitigation in place |
|---|---|
| Registration spam / D1 exhaustion | 10/min/IP register cap; 16 KB body cap; wildcard CORS removed (no drive-by browser abuse); maintenance kill switch |
| Pairing code brute force | 10/min/IP on pair-link; codes single-use, 5-min TTL, crypto-random |
| Rogue token flooding alerts | 30/min/user; thief bypass keeps safety but capped at 120/min/IP; >=50 failed auths/hour/token-hash -> instant in-memory deny |
| Admin credential brute force | 5 failed logins/min/IP; constant-time compare (node); hashed sessions, 1 h TTL |
| Stolen database | Tokens stored only as SHA-256 hashes; audit IPs are operator-side only |
| XSS via device names | Every dashboard interpolation HTML-escaped (tested); strict CSP meta on both dashboards |
| Clickjacking / MIME sniffing | X-Frame-Options: DENY + nosniff on every response |
| Supply chain | lockfile installs; npm audit + pip-audit in CI (warn-first); no runtime network fetches in app |
| Incident response | MAINTENANCE_MODE valve closes /api/* without redeploying |

Known accepted risks: per-IP limiters are in-memory/per-isolate on the CF
worker (multi-colloid attackers can spread across isolates); the deny-set is
per-process on relay-node. Both are documented trade-offs -- the safety path
(THIEF_ALERT) always fails open.
