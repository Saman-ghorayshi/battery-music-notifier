// Security hardening tests: pair brute shield, oversize bodies, rogue-token
// containment, maintenance valve, security headers, no wildcard CORS.
// One outer suite so the shared pg pool is closed exactly once at the end.
const test = require("node:test");
const assert = require("node:assert");

process.env.PORT = "0";
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
delete process.env.MAINTENANCE_MODE;

const request = require("supertest");
const { Pool } = require("pg");

test("security hardening", async (t) => {
  // bail out cleanly when the database is down
  {
    const probe = new Pool({ connectionString: process.env.DATABASE_URL });
    try {
      await probe.query("SELECT 1 FROM daily_stats LIMIT 1");
    } catch (e) {
      console.log("# database not reachable, skipping:", e.message);
      t.skip("needs migrated postgres");
      return;
    } finally {
      await probe.end();
    }
  }

  const { start } = require("../src/server");
  const server = await start();
  const base = `http://127.0.0.1:${server.address().port}`;
  t.after(async () => {
    server.close();
    await new Promise((r) => setTimeout(r, 50));
    await require("../src/db").end(); // close shared pool sockets last
  });

  await t.test("no wildcard CORS anywhere", async () => {
    const pre = await request(base).options("/api/alert");
    assert.equal(pre.status, 204);
    assert.ok(!("access-control-allow-origin" in pre.headers), "ACAO leaked on OPTIONS");
    const get = await request(base).get("/health");
    assert.ok(!get.headers["access-control-allow-origin"], "ACAO leaked on GET");
  });

  await t.test("security headers present", async () => {
    const r = await request(base).get("/health");
    assert.equal(r.headers["x-content-type-options"], "nosniff");
    assert.equal(r.headers["x-frame-options"], "DENY");
    assert.equal(r.headers["referrer-policy"], "no-referrer");
  });

  await t.test("oversize body rejected, never 500", async () => {
    const r = await request(base)
      .post("/api/register")
      .set("Content-Type", "application/json")
      .send('{"device_name":"' + "A".repeat(20000) + '"}');
    assert.ok([400, 413].includes(r.status), `got ${r.status}`);
  });

  await t.test("rogue token contained after repeated failures", async () => {
    const bad = "f".repeat(48);
    let last;
    for (let i = 0; i < 55; i++) {
      last = await request(base)
        .get("/api/poll")
        .set({ Authorization: `Bearer ${bad}` });
      if (last.status === 403 && last.body.error === "denied") break;
    }
    assert.equal(last.status, 403);
    assert.equal(last.body.error, "denied", "expected deny-set response");
  });

  await t.test("pair-link brute force capped at 10/min per ip", async () => {
    let saw429 = false;
    for (let i = 0; i < 14; i++) {
      const r = await request(base)
        .post("/api/pair/link")
        .send({ code: String(100000 + i * 7) });
      if (r.status === 429) saw429 = true;
      else assert.ok([400, 404].includes(r.status), `unexpected ${r.status}`);
    }
    assert.ok(saw429, "pair brute force was not capped");
  });

  await t.test("maintenance valve: /api closes, /health stays", async () => {
    process.env.MAINTENANCE_MODE = "1"; // middleware reads env dynamically
    try {
      const reg = await request(base)
        .post("/api/register")
        .send({ device_name: "m", platform: "m" });
      assert.equal(reg.status, 503);
      assert.equal(reg.body.error, "maintenance");
      const health = await request(base).get("/health");
      assert.equal(health.status, 200);
    } finally {
      delete process.env.MAINTENANCE_MODE;
    }
  });
});
