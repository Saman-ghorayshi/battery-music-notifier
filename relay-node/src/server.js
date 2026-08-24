// Battery Relay -- Node.js/Express + PostgreSQL.
// Drop-in self-hosted alternative to the Cloudflare Worker: identical API,
// identical security model (hashed tokens, throttles, bounded event log).
const express = require("express");
const config = require("./config");
const pool = require("./db");

const app = express();
app.disable("x-powered-by");
app.use(express.json({ limit: "16kb" })); // payloads are tiny; cap abuse

// CORS parity with worker.js (permissive: clients may live anywhere).
app.use((req, res, next) => {
  res.set({
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
    "Cache-Control": "no-store",
  });
  if (req.method === "OPTIONS") return res.status(204).end();
  next();
});

app.use(require("./routes/health"));
app.use(require("./routes/api"));
app.use(require("./routes/pair"));
app.use(require("./routes/admin"));

// 404 + error handling in the workers' JSON dialect.
app.use((req, res) => res.status(404).json({ ok: false, error: "not_found" }));
app.use((err, _req, res, _next) => {
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
