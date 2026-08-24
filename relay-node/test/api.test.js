// Integration tests against a real Postgres. If the DB is not reachable the
// suite skips so `npm test` still works without docker.
// Setup: docker compose up -d db && npm run migrate
const test = require("node:test");
const assert = require("node:assert");

process.env.PORT = "0"; // ephemeral port per test run
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
process.env.RATE_LIMIT_ENABLED = "false"; // throttles would flake the tests

const request = require("supertest");
const { Pool } = require("pg");

async function newUser(base, name = "test-laptop") {
  const r = await request(base)
    .post("/api/register")
    .send({ device_name: name, platform: "test" });
  assert.equal(r.status, 200);
  assert.match(r.body.token, /^[0-9a-f]{48}$/);
  return r.body.token;
}

test("relay api", async (t) => {
  // bail out cleanly when there is no database
  {
    const pool = new Pool({ connectionString: process.env.DATABASE_URL });
    try {
      await pool.query("SELECT 1");
    } catch (e) {
      console.log("# database not reachable:", e.message);
      t.skip("needs a running postgres (docker compose up -d db)");
      return;
    } finally {
      await pool.end();
    }
  }

  const { start } = require("../src/server");
  const server = await start();
  const base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => server.close());

  await t.test("health page looks boring", async () => {
    const r = await request(base).get("/health");
    assert.equal(r.status, 200);
    assert.ok(r.text.includes("<h1>OK</h1>"));
  });

  await t.test("register -> poll, plaintext token never stored", async () => {
    const token = await newUser(base);
    const p = await request(base)
      .get("/api/poll")
      .set({ Authorization: `Bearer ${token}` });
    assert.equal(p.status, 200);
    assert.equal(p.body.alert_active, 0);

    const pool = new Pool({ connectionString: process.env.DATABASE_URL });
    const { rows } = await pool.query(
      "SELECT COUNT(*)::int AS cnt FROM users WHERE token = $1",
      [token],
    );
    await pool.end();
    assert.equal(rows[0].cnt, 0, "plaintext token found in db!");
  });

  await t.test("bad token rejected with 401", async () => {
    const r = await request(base)
      .get("/api/poll")
      .set({ Authorization: `Bearer ${"a".repeat(48)}` });
    assert.equal(r.status, 401);
  });

  await t.test("alert shows up on poll, then clears", async () => {
    const token = await newUser(base);
    const h = { Authorization: `Bearer ${token}` };

    const a = await request(base)
      .post("/api/alert")
      .set(h)
      .send({ alert_type: "THIEF_ALERT", battery_pct: 42, is_charging: false });
    assert.equal(a.status, 200);

    const poll = await request(base).get("/api/poll").set(h);
    assert.equal(poll.body.alert_active, 1);
    assert.equal(poll.body.battery_pct, 42);

    await request(base).post("/api/clear").set(h);
    const poll2 = await request(base).get("/api/poll").set(h);
    assert.equal(poll2.body.alert_active, 0);
  });

  await t.test("pairing flow: bad code, link once, replay dies", async () => {
    const token = await newUser(base);
    const g = await request(base)
      .post("/api/pair/generate")
      .set({ Authorization: `Bearer ${token}` })
      .send({});
    const code = g.body.code;
    assert.match(code, /^\d{6}$/);

    const malformed = await request(base).post("/api/pair/link").send({ code: "abc123" });
    assert.equal(malformed.status, 400);

    const link = await request(base).post("/api/pair/link").send({ code });
    assert.equal(link.status, 200);
    assert.match(link.body.token, /^[0-9a-f]{48}$/);

    // linked token polls the same account
    const p = await request(base)
      .get("/api/poll")
      .set({ Authorization: `Bearer ${link.body.token}` });
    assert.equal(p.status, 200);

    // single use
    const replay = await request(base).post("/api/pair/link").send({ code });
    assert.equal(replay.status, 404);
  });

  await t.test("admin login + stats + ban/unban", async () => {
    // unique marker: the db keeps old runs' users around, find() must not
    // match one of those or we ban a stranger and our token stays valid
    const marker = `test-laptop-${Date.now()}`;
    const token = await newUser(base, marker);
    const login = await request(base)
      .post("/admin/login")
      .send({ admin_key: process.env.ADMIN_KEY });
    assert.equal(login.status, 200);
    const h = { Authorization: `Bearer ${login.body.session_key}` };

    const wrong = await request(base)
      .post("/admin/login")
      .send({ admin_key: "wrong-wrong-wrong" });
    assert.equal(wrong.status, 401);

    const s = await request(base).get("/admin/stats").set(h);
    assert.equal(s.status, 200);
    assert.ok(s.body.stats.total_users >= 1);

    const me = s.body.recent_users.find((u) => u.device_name === marker);
    assert.ok(me, "registered user missing from recent_users");
    const ban = await request(base).post("/admin/ban").set(h).send({ user_id: me.user_id });
    assert.equal(ban.status, 200);

    // banned device gets a clear 403 "banned", not a generic 401
    const poll = await request(base)
      .get("/api/poll")
      .set({ Authorization: `Bearer ${token}` });
    assert.equal(poll.status, 403);
    assert.equal(poll.body.error, "banned");

    const unban = await request(base)
      .post("/admin/unban")
      .set(h)
      .send({ user_id: me.user_id });
    assert.equal(unban.status, 200);
  });

  await t.test("unknown route -> json 404", async () => {
    const r = await request(base).get("/api/nope");
    assert.equal(r.status, 404);
    assert.equal(r.body.error, "not_found");
  });
});
