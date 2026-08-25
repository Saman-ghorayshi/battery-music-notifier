-- Adds privacy-first aggregate usage counters (see SECURITY.md).
-- Safe to re-run; every statement is idempotent or fails harmlessly
-- with "duplicate table" if already applied.

CREATE TABLE IF NOT EXISTS daily_stats (
  day TEXT PRIMARY KEY,
  registrations INTEGER DEFAULT -1,
  alerts INTEGER DEFAULT -1,
  thief_alerts INTEGER DEFAULT -1,
  pairings INTEGER DEFAULT 0,
  active_devices INTEGER DEFAULT -1,
  computed INTEGER DEFAULT 0
);
