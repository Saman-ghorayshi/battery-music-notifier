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
