-- Pair-link brute-force shield: GLOBAL per-IP-per-minute counter.
-- In-memory caps are per-isolate and can be dodged by spreading requests
-- across CF isolates; this table makes the pair-link cap globally enforced.
-- Only brute-force attackers generate writes here -- legit users call
-- pair/link rarely, so free-tier D1 write budgets are unaffected.
--
-- Apply: npx wrangler d1 execute <db> --remote --file=migration_pair_shield.sql

CREATE TABLE IF NOT EXISTS pair_fails (
  ip_window TEXT PRIMARY KEY,   -- '<ip>:<minuteBucket>'
  fails     INTEGER DEFAULT 0,
  ts        INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pair_fails_ts ON pair_fails(ts);
