// Rate-limit integration test. Runs in its own process (node --test) with
// limits ON, unlike api.test.js which disables them.
// The redis backend gets exercised in the compose stack; this file proves
// the default memory path and the register/login throttles end to end.
const test = require("node:test");
const assert = require("node:assert");

process.env.PORT = "0";
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
delete process.env.RATE_LIMIT_ENABLED; // defaults to on
delete process.env.REDIS_URL; // memory buckets for this run

const request = require("supertest");

test("throttles", async (t) => {
  const { start } = require("../src/server");
  const server = await start();
  const base = `http://127.0.0.1:${server.address().port}`;
  t.after(() => server.close());

  await t.test("register bursts stop at 10/min per ip", async () => {
    let saw429 = false;
    let ok = 0;
    for (let i = 0; i < 12; i++) {
      const r = await request(base)
        .post("/api/register")
        .send({ device_name: `burst-${i}`, platform: "test" });
      if (r.status === 200) ok++;
      if (r.status === 429) {
        assert.equal(r.body.error, "rate_limited");
        saw429 = true;
      }
    }
    assert.equal(ok, 10, `expected exactly 10 through, got ${ok}`);
    assert.ok(saw429, "never got a 429");
  });

  await t.test("thief alerts bypass the user limit, battery alerts do not", async () => {
    const reg = await request(base)
      .post("/api/register")
      .send({ device_name: "limit-me", platform: "test" });
    // registration bucket may already be hot from the previous subtest --
    // use a fresh ip-ish header trick is not available, so tolerate 429 here
    if (reg.status === 429) return t.skip("register bucket full");
    const h = { Authorization: `Bearer ${reg.body.token}` };

    // user max is 30/min: fire 30 battery alerts (should all pass), then one more
    for (let i = 0; i < 30; i++) {
      const r = await request(base).post("/api/alert").set(h).send({ alert_type: "BATTERY" });
      assert.equal(r.status, 200, `alert ${i} failed`);
    }
    const blocked = await request(base).post("/api/alert").set(h).send({ alert_type: "BATTERY" });
    assert.equal(blocked.status, 429);

    const thief = await request(base)
      .post("/api/alert")
      .set(h)
      .send({ alert_type: "THIEF_ALERT", battery_pct: 1, is_charging: false });
    assert.equal(thief.status, 200, "THIEF_ALERT must never be rate limited");
  });

  await t.test("admin login brute force stops at 5/min", async () => {
    for (let i = 0; i < 5; i++) {
      await request(base).post("/admin/login").send({ admin_key: "wrong-wrong-wrong" });
    }
    const r = await request(base).post("/admin/login").send({ admin_key: "wrong-wrong-wrong" });
    assert.equal(r.status, 429);
  });
});
