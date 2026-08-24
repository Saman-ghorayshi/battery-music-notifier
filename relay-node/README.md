# battery-relay (Node + Postgres)

Self-hosted relay server for Battery Music Notifier. Same API and same
security model as the Cloudflare Worker in `worker/`, but on plain
Node.js/Express with PostgreSQL instead of D1.

Point your devices at it by setting `worker_url` in the app config (or
answering "n" to the hosted worker question during `battery-music init`).
Nothing else changes - register, alerts, polling, thief catcher, pairing
and the admin CLI all work exactly the same.

## Quick start

    cp .env.example .env       # set ADMIN_KEY to something long + random
    docker compose up -d db    # or use your own postgres
    npm install
    npm run migrate            # creates tables
    npm start                  # listens on :8787

Or all-in-one with Docker:

    docker compose up -d --build

Health check is just `GET /health`.

## Config (.env)

- `DATABASE_URL` - postgres connection string
- `ADMIN_KEY` - admin secret, minimum 10 chars or admin login refuses to work
- `PORT` - default 8787
- `RATE_LIMIT_ENABLED` - set to `false` for a private single-user instance.
  THIEF_ALERT bypasses rate limiting either way, that one must never be blocked.

## What matches the CF worker

- tokens are random 48-char hex, only sha256 hashes go in the database,
  plaintext shown once at register / pair-link
- pairing codes hold a user_id, not a token; linking mints a fresh linked
  token and re-linking rotates it (old phone gets kicked)
- throttles: 30 req/min per user, 10 registrations/min per IP, 5 failed
  admin logins/min per IP (in-memory buckets, reset on restart)
- event log trimmed to 200 rows per user
- banned users get a clear 403 "banned" instead of generic 401
- no server-side push of any kind - clients handle their own notifications

The rate limit buckets live in process memory here, so if you run multiple
instances behind a load balancer each one counts separately. For serious
multi-instance deployments swap `src/util.js` buckets for Redis, everything
else stays the same.

## Endpoints

Same as worker/README.md:

    POST /api/register          { device_name, platform } -> { token, user_id }
    POST /api/ping              keep-alive
    POST /api/alert             { alert_type, battery_pct, is_charging }
    POST /api/clear
    GET  /api/poll
    POST /api/pair/generate     -> { code }
    POST /api/pair/link         { code } -> { token }
    POST /admin/login           { admin_key } -> { session_key }
    GET  /admin/stats
    POST /admin/ban | unban     { user_id }
    POST /admin/broadcast       { alert_type }
    POST /admin/clear-all

Auth is `Authorization: Bearer <token>` everywhere except register and
pair/link.

## Tests

Integration tests need a reachable Postgres (they skip themselves if the DB
is down):

    docker compose up -d db
    DATABASE_URL=postgres://battery:battery@127.0.0.1:55432/battery npm test

## Deploying elsewhere

Any Node 18+ host works. Railway/Render/Fly: set the env vars from .env
example, point DATABASE_URL at their managed Postgres, run `npm run migrate`
once as a release command, done.

## Roadmap

- HTML admin dashboard like the worker has (CLI admin already works today)
- optional Turnstile check on register
