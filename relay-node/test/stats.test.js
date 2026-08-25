// Daily-stats rollup tests against a real Postgres (compose db).
// Proves the three capture strategies and, most importantly, that a frozen
// day survives event trimming.
const test = require("node:test");
const assert = require("node:assert");

process.env.PORT = "0";
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
process.env.RATE_LIMIT_ENABLED = "false";

const request = require("supertest");
const { Pool } = require("pg");

test("daily stats rollup", async (t) => {
  // bail out cleanly when the migration hasn't run / db is down
  {
    const pool = new Pool({ connectionString: process.env.DATABASE_URL });
    try {
      await pool.query("SELECT 1 FROM daily_stats LIMIT 1");
    } catch (e) {
      console.log("# skipping:", e.message);
      t.skip("needs migrated postgres (npm run migrate)");
      return;
    } finally {
      await pool.end();
    }
  }

  const { start } = require("../src/server");
  const server = await start();
  const base = `http://127.0.0.1:${server.address().port}`;
    t.after(async () => {
    server.close();
    await new Promise((r) => setTimeout(r, 50));
    await require("../src/db").end();
  });

  const pool = new Pool({ connectionString: process.env.DATABASE_URL });

  const tag = `stats-${Date.now()}`; // unique per run
  // derive days EXACTLY like src/stats.js does -- a naive Date.now()-86400000
  // crosses the UTC boundary differently and points at the wrong bucket
  const todayStr = () => new Date().toISOString().slice(0, 10);
  const dayOffset = (iso, delta) => {
    const d = new Date(iso + "T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + delta);
    return d.toISOString().slice(0, 10);
  };
  const today = todayStr();
  const yesterday = dayOffset(today, -1);
  const epochOf = (day) => Math.floor(new Date(day + "T12:00:00Z").getTime() / 1000);

  // cleanup must survive assertion failures, or leaked seeds poison reruns
  t.after(async () => {
    try {
      await pool.query("DELETE FROM users WHERE device_name = $1", [tag]);
      await pool.query(
        "DELETE FROM pairing_codes WHERE user_id NOT IN (SELECT user_id FROM users)");
    } catch (_) { /* best effort */ }
    await pool.end();
  });

  await t.test("yesterday computes and freezes", async () => {
    // make the bucket hermetic: drop every user dated "yesterday" (dev-box
    // junk incl. our own past failures; events cascade). Absolutes stable.
    await pool.query(
      "DELETE FROM users WHERE to_char(to_timestamp(created_at),'YYYY-MM-DD') = $1",
      [yesterday]);
    await pool.query("DELETE FROM daily_stats WHERE day = $1", [yesterday]);

    for (let i = 0; i < 2; i++) {
      await pool.query(
        "INSERT INTO users (token, device_name, created_at) VALUES ($1, $2, $3)",
        [`${tag}-y-${i}-${"ab".repeat(12)}`, tag, epochOf(yesterday)],
      );
    }

    const u = await pool.query(
      "SELECT user_id FROM users WHERE token = $1",
      [`${tag}-y-0-${"ab".repeat(12)}`],
    );
    for (let i = 0; i < 3; i++) {
      await pool.query(
        "INSERT INTO events (user_id, event_type, ts) VALUES ($1, $2, $3)",
        [u.rows[0].user_id, i === 0 ? "THIEF_ALERT" : "BATTERY", epochOf(yesterday)],
      );
    }

    const { ensureDailyStats } = require("../src/stats");
    await ensureDailyStats(true);

    const yRow = (await pool.query(
      "SELECT * FROM daily_stats WHERE day = $1", [yesterday],
    )).rows[0];
    assert.equal(yRow.registrations, 2, "registrations");
    assert.equal(yRow.alerts, 3, "alerts delta");
    assert.equal(yRow.thief_alerts, 1, "thief delta");
    assert.equal(yRow.computed, 1, "yesterday must be frozen");

    // freeze proof: wipe yesterday's events, re-roll, numbers survive
    await pool.query("DELETE FROM events WHERE user_id = $1", [u.rows[0].user_id]);
    await ensureDailyStats(true);
    const after = (await pool.query(
      "SELECT alerts FROM daily_stats WHERE day = $1", [yesterday],
    )).rows[0];
    assert.equal(after.alerts, yRow.alerts, "frozen day was rewritten by rollup!");
  });

  await t.test("pairing increments inline counter", async () => {
    const me = await pool.query(
      "INSERT INTO users (token, device_name, created_at) VALUES ($1, $2, $3) RETURNING user_id",
      [`${tag}-link-${"cd".repeat(12)}`, tag, epochOf(today)],
    );
    const code = "9" + String(Date.now()).slice(-5); // unique-ish 6 digits
    await pool.query(
      "INSERT INTO pairing_codes (code, user_id, expires_at) VALUES ($1, $2, $3)",
      [code, me.rows[0].user_id, epochOf(today) + 3600],
    );
    const before = (await pool.query(
      "SELECT pairings FROM daily_stats WHERE day = $1", [today],
    )).rows[0]?.pairings ?? 0;

    const r = await request(base).post("/api/pair/link").send({ code });
    assert.equal(r.status, 200);

    const after = (await pool.query(
      "SELECT pairings FROM daily_stats WHERE day = $1", [today],
    )).rows[0].pairings;
    assert.equal(after, before + 1, "pairing counter did not increment");
  });

  await t.test("admin stats exposes the daily array", async () => {
    const login = await request(base)
      .post("/admin/login")
      .send({ admin_key: process.env.ADMIN_KEY });
    const s = await request(base)
      .get("/admin/stats")
      .set({ Authorization: `Bearer ${login.body.session_key}` });
    assert.equal(s.status, 200);
    assert.ok(Array.isArray(s.body.daily), "daily array missing from /admin/stats");
    assert.ok(s.body.daily.some((d) => d.day === today), "today missing from daily");
  });

  // cleanup handled in t.after above
});

