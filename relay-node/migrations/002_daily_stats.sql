-- Privacy-first aggregate usage counters (parity with worker/schema.sql).
-- A day's row is computed while young, then frozen via computed=1 so event
-- trimming can never rewrite history.

CREATE TABLE IF NOT EXISTS daily_stats (
  day TEXT PRIMARY KEY,
  registrations INTEGER DEFAULT -1,
  alerts INTEGER DEFAULT -1,
  thief_alerts INTEGER DEFAULT -1,
  pairings INTEGER DEFAULT 0,
  active_devices INTEGER DEFAULT -1,
  computed INTEGER DEFAULT 0
);
