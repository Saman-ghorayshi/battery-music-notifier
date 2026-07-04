# Battery Relay Worker

Two deployment modes, same worker.js codebase:

## Mode 1: Hosted (for non-technical users)

You deploy the worker on your domain. Users just install the app and it works.
Their config defaults to your worker URL automatically. No setup needed.

Rate limiting is enabled (30 req/min/user) to protect your worker from abuse.
THIEF_ALERT always bypasses rate limiting -- a thief unplugging a phone must
get through immediately, even if the user has been polling heavily.

### Deploy (Hosted)

```bash
cd worker/
npx wrangler d1 create battery-relay-db
# Copy database_id into wrangler.toml
npx wrangler d1 execute battery-relay-db --file=schema.sql --remote
npx wrangler secret put ADMIN_KEY    # Set a long random secret
npx wrangler deploy
```

Then edit `battery_notifier/config.py` and change `DEFAULT_WORKER_URL`
to your deployed worker URL. Users who install the package will use it
automatically.

### Obscurity (recommended)

Route through a throwaway domain:
- Cloudflare Dashboard -> Workers -> your-worker -> Triggers -> Custom Domain
- Or: Workers -> Routes -> `yourdomain.com/battery/*`

The health endpoint at `/` returns a generic "OK" page, not an API description.

## Mode 2: Self-Hosted (for paranoid users)

Users deploy their own worker. No rate limiting, full control, private data.

```bash
cd worker/self-hosted/
# Edit wrangler.toml: set database_id, change ADMIN_KEY
npx wrangler d1 create battery-relay-db-private
npx wrangler d1 execute battery-relay-db-private --file=../schema.sql --remote
npx wrangler secret put ADMIN_KEY
npx wrangler deploy
```

Then in the app:
```bash
battery-music init
# When asked "Use default hosted worker?" -> answer "n"
# Enter your self-hosted worker URL
```

Self-hosted workers set `RATE_LIMIT_ENABLED = "false"` in wrangler.toml.
THIEF_ALERT still bypasses rate limiting as a safety guarantee, but all
other requests are unlimited.

## API Endpoints

### Public (requires Bearer token)
- POST /api/register    -- { device_name, platform } -> { token, user_id }
- POST /api/ping        -- keep-alive
- POST /api/alert       -- { alert_type, battery_pct, is_charging }
- POST /api/clear       -- clear alert
- GET  /api/poll        -- { alert_active, alert_type, alert_ts, battery_pct, is_charging }

### Admin (requires session key from /admin/login)
- POST /admin/login     -- { admin_key } -> { session_key }
- GET  /admin           -- HTML dashboard (stats, ban, broadcast)
- GET  /admin/stats     -- JSON stats
- POST /admin/ban       -- { user_id }
- POST /admin/unban     -- { user_id }
- POST /admin/broadcast -- { alert_type } (force alert all users)
- POST /admin/clear-all -- clear all alerts

## Security

- 24-byte random tokens (Web Crypto API)
- Bearer auth on every API call
- Rate limiting: 30 req/min/user (hosted only, THIEF_ALERT exempt)
- Admin sessions: SHA-256 hashed, 1-hour TTL, expired sessions auto-cleaned from D1
- Admin stats API excludes the `token` column -- user auth tokens are never exposed in dashboard data
- Banned users blocked at auth layer
- D1 database (SQLite, scales to 10k-50k users)
- Event log bounded at 200 events per user
- Health endpoint obscures API purpose
