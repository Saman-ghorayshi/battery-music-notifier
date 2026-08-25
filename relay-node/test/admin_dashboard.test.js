// HTML admin dashboard tests: auth gate, XSS escaping, sparkline, audit feed.
// Own process via node --test; skips cleanly without postgres.
const test = require("node:test");
const assert = require("node:assert");

process.env.PORT = "0";
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
process.env.RATE_LIMIT_ENABLED = "false";

const request = require("supertest");
const { Pool } = require("pg");

test("admin dashboard", async (t) => {
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
    await require("../src/db").end();
  });

  const tag = `dash-${Date.now()}`;
  const evilName = `<script>alert(1)</script>${tag}`;

  // register a hostile-named device straight through the public API
  const reg = await request(base)
    .post("/api/register")
    .send({ device_name: evilName, platform: "linux" });
  assert.equal(reg.status, 200);
  const evilUid = reg.body.user_id;

  // unauthenticated -> login page, no stats leak
  const anon = await request(base).get("/admin");
  assert.equal(anon.status, 401);
  assert.ok(anon.text.includes("Admin Login"), "login page missing");
  assert.ok(!anon.text.includes("<polyline"), "stats leaked on login page");

  // session flow
  const login = await request(base)
    .post("/admin/login")
    .send({ admin_key: process.env.ADMIN_KEY });
  assert.equal(login.status, 200);
  const h = { Authorization: `Bearer ${login.body.session_key}` };

  const page = await request(base).get("/admin").set(h);
  assert.equal(page.status, 200);

  // XSS must be escaped
  assert.ok(
    !page.text.includes(`<script>alert(1)</script>${tag}`),
    "raw hostile device name reached the dashboard!",
  );
  assert.ok(
    page.text.includes("&lt;script&gt;"),
    "escaped device name not found",
  );

  // sparkline + stats cards present
  assert.ok(page.text.includes("<polyline"), "sparkline missing");
  assert.ok(page.text.includes("Total Users"), "stat cards missing");

  // ban button targets exist for our hostile user
  assert.ok(page.text.includes(`data-uid="${evilUid}"`), "user row missing");

  // audit json endpoint: shape + newest-first with our actions present later?
  // (ban/unban happen below; here just verify shape)
  const a0 = await request(base).get("/admin/audit.json?lines=50").set(h);
  assert.equal(a0.status, 200);
  assert.ok(Array.isArray(a0.body.events), "audit events not an array");

  // ban via JSON api, then confirm dashboard reflects BANNED state
  await request(base).post("/admin/ban").set(h).send({ user_id: evilUid });

  const page2 = await request(base).get("/admin").set(h);
  assert.ok(page2.text.includes("BANNED"), "banned state not shown");
});
