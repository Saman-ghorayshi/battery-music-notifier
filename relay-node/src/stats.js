// Daily aggregate stats (privacy-first: events, never people).
// Parity with the CF Worker's ensureDailyStats -- see worker/worker.js.
//
// A day's row is computed while young and frozen (computed=1) the first time
// it is no longer today, so event trimming can never rewrite history.
const pool = require("./db");
const { now } = require("./util");

const LOOKBACK_DAYS = 7;
let rolledDay = "";

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function dayOffset(iso, delta) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

async function ensureDailyStats(force = false) {
  const today = todayStr();
  if (!force && rolledDay === today) return;
  const client = await pool.connect();
  try {
    const days = [];
    for (let i = 0; i < LOOKBACK_DAYS; i++) days.push(dayOffset(today, -i));

    await client.query(
      `INSERT INTO daily_stats (day) SELECT * FROM unnest($1::text[])
       ON CONFLICT (day) DO NOTHING`,
      [days],
    );

    // -1 marks "not computed yet"; today's row keeps computed=0 so it
    // recomputes all day, then freezes on tomorrow's first rollup.
    await client.query(
      `UPDATE daily_stats ds SET
         registrations  = (SELECT COUNT(*) FROM users
                           WHERE to_char(to_timestamp(created_at), 'YYYY-MM-DD') = ds.day),
         alerts         = COALESCE((SELECT COUNT(*) FROM events e
                           WHERE to_char(to_timestamp(e.ts), 'YYYY-MM-DD') = ds.day), 0),
         thief_alerts   = COALESCE((SELECT COUNT(*) FROM events e
                           WHERE to_char(to_timestamp(e.ts), 'YYYY-MM-DD') = ds.day
                             AND e.event_type = 'THIEF_ALERT'), 0),
         active_devices = CASE WHEN ds.day = $1 THEN
                            (SELECT COUNT(*) FROM users WHERE last_seen > $2)
                          ELSE ds.active_devices END,
         computed       = CASE WHEN ds.day = $1 THEN 0 ELSE 1 END
       WHERE ds.day = ANY($3::text[]) AND ds.computed = 0`,
      [today, now() - 86400, days],
    );

    rolledDay = today;
  } finally {
    client.release();
  }
}

async function incrPairings() {
  await pool.query(
    `INSERT INTO daily_stats (day, pairings) VALUES ($1, 1)
     ON CONFLICT (day) DO UPDATE SET pairings = daily_stats.pairings + 1`,
    [todayStr()],
  );
}

module.exports = { ensureDailyStats, incrPairings };
