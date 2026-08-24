// Audit trail test: admin actions must land as parseable JSONL.
// Own process via node --test, own AUDIT_FILE so it never touches real logs.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");

process.env.PORT = "0";
process.env.DATABASE_URL =
  process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery";
process.env.ADMIN_KEY = process.env.ADMIN_KEY || "test-admin-key-123";
process.env.RATE_LIMIT_ENABLED = "false";

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "relay-audit-"));
process.env.AUDIT_FILE = path.join(tmp, "audit.log");

const request = require("supertest");

test("admin actions are audited as jsonl", async () => {
  const { start } = require("../src/server");
  const server = await start();
  const base = `http://127.0.0.1:${server.address().port}`;

  await request(base).post("/admin/login").send({ admin_key: "nope-nope-nope" }); // fail
  const login = await request(base)
    .post("/admin/login")
    .send({ admin_key: process.env.ADMIN_KEY }); // ok
  assert.equal(login.status, 200);
  const h = { Authorization: `Bearer ${login.body.session_key}` };

  const reg = await request(base)
    .post("/api/register")
    .send({ device_name: "audit-target", platform: "test" });
  const stats = await request(base).get("/admin/stats").set(h);
  const me = stats.body.recent_users.find((u) => u.device_name === "audit-target");
  await request(base).post("/admin/ban").set(h).send({ user_id: me.user_id });
  await request(base).post("/admin/unban").set(h).send({ user_id: me.user_id });

  server.close();
  // appendFileSync is sync; give the event loop one tick then read
  await new Promise((r) => setTimeout(r, 100));

  const lines = fs.readFileSync(process.env.AUDIT_FILE, "utf8").trim().split("\n");
  const events = lines.map((l) => JSON.parse(l)); // throws if any line is not json
  const actions = events.map((e) => e.action);

  assert.ok(actions.includes("admin_login_failed"), "failed login not audited");
  assert.ok(actions.includes("admin_login"), "login not audited");
  assert.ok(actions.includes("banned"), "ban not audited");
  assert.ok(actions.includes("unbanned"), "unban not audited");

  for (const e of events) {
    assert.ok(e.ts && e.ip !== undefined, `missing ts/ip in ${JSON.stringify(e)}`);
  }

  fs.rmSync(tmp, { recursive: true, force: true });
});
