-- Device registry: one row per presenting token (laptop + each paired phone),
-- keyed by the sha256 of the token itself. Powers /api/poll's "other_devices"
-- list so you can see which of your devices are still alive.
--
-- Also adds users.alert_origin: the token hash that raised the current alert.
-- The device that raised a THIEF alert may not silence it (a thief holding
-- that device must not stop the alarm); clears from the other paired device
-- and BATTERY alerts still work as before.
--
-- Apply: npx wrangler d1 execute <db> --remote --file=migration_devices.sql
-- NOTE: the ALTER TABLE fails if alert_origin already exists -- that just
-- means this migration ran before; verify the column and move on.

CREATE TABLE IF NOT EXISTS devices(user_id INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL, name TEXT, platform TEXT, last_seen INTEGER DEFAULT 0);

CREATE INDEX IF NOT EXISTS idx_devices_user ON devices(user_id);

ALTER TABLE users ADD COLUMN alert_origin TEXT;
