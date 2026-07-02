-- Battery Notifier Cloud Relay - D1 Schema
-- Handles 10k-50k users with per-user token auth and rate limiting

CREATE TABLE IF NOT EXISTS users (
  user_id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,
  device_name TEXT DEFAULT '',
  platform TEXT DEFAULT '',
  created_at INTEGER NOT NULL,
  last_seen INTEGER DEFAULT 0,
  is_banned INTEGER DEFAULT 0,
  is_founding INTEGER DEFAULT 0,
  alert_active INTEGER DEFAULT 0,
  alert_type TEXT DEFAULT '',
  alert_ts INTEGER DEFAULT 0,
  battery_pct INTEGER DEFAULT -1,
  is_charging INTEGER DEFAULT 0,
  total_alerts INTEGER DEFAULT 0,
  is_pro INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  payload TEXT DEFAULT '',
  ts INTEGER NOT NULL,
  FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_users_token ON users(token);
CREATE INDEX IF NOT EXISTS idx_users_alert ON users(alert_active);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);

-- Optional: sessions table for admin auth (single admin key)
CREATE TABLE IF NOT EXISTS admin_sessions (
  session_key TEXT PRIMARY KEY,
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL
);
