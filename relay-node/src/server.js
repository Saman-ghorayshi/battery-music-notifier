// Battery Relay -- Node.js/Express + PostgreSQL.
// Drop-in self-hosted alternative to the Cloudflare Worker: identical API,
// identical security model (hashed tokens, throttles, bounded event log).
const express = require("express");
const config = require("./config");
const pool = require("./db");

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "16kb" })); // payloads are tiny; cap abuse

// Security headers on everything. No CORS by design: native clients ignore
// it and the dashboard is same-origin, so wildcard only helped abusers.
app.use((req, res, next) => {
  res.set({
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
  });
  if (req.method === "OPTIONS") return res.status(204).end();
  next();
});

// Incident kill switch: /api/* closes; health + admin stay reachable.
// Reads env dynamically so tests (and ops) can flip it without restart.
app.use((req, res, next) => {
  if (process.env.MAINTENANCE_MODE === "1" && req.path.startsWith("/api/")) {
    return res.status(503).json({ ok: false, error: "maintenance" });
  }
  next();
});

app.use(require("./routes/health"));
app.use(require("./routes/api"));
app.use(require("./routes/pair"));
// HTML dashboard first: it owns GET /admin + /admin/audit.json; everything
// else falls through to the JSON admin API (CLI compatibility).
app.use(require("./routes/admin_dashboard"));
app.use(require("./routes/admin"));

// 404 + error handling in the workers' JSON dialect.
app.use((req, res) => res.status(404).json({ ok: false, error: "not_found" }));
app.use((err, _req, res, _next) => {
  if (err.type === "entity.too.large" || err.statusCode === 413) {
    return res.status(413).json({ ok: false, error: "payload_too_large" });
  }
  if (err.type === "entity.parse.failed") {
    return res.status(400).json({ ok: false, error: "invalid_body" });
  }
  console.error("[server]", err.message);
  res.status(500).json({ ok: false, error: "internal_error" });
});

async function start() {
  // Fail fast if the DB is unreachable or migrations are missing.
  await pool.query("SELECT 1 FROM schema_migrations LIMIT 1");
  await require("./rateLimit").initRateLimit();

  const server = app.listen(config.port, () => {
    const backend = config.redisUrl ? "redis" : "memory";
    console.log(`Battery relay listening on :${config.port} (limits: ${backend}, ${config.rateLimitEnabled ? "on" : "off"})`);
  });
  server.keepAliveTimeout = 65_000; // behind proxies that use HTTP keep-alive
  return server;
}

if (require.main === module) {
  start().catch((err) => {
    console.error(`Failed to start: ${err.message}`);
    console.error("Run `npm run migrate` first and check DATABASE_URL.");
    process.exit(1);
  });
}

module.exports = { app, start };
