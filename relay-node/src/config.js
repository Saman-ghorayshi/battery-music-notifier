// Environment configuration -- everything overridable via env/.env.
require("dotenv").config();

function num(name, def) {
  const v = parseInt(process.env[name], 10);
  return Number.isFinite(v) ? v : def;
}

module.exports = {
  port: num("PORT", 8787),
  // 127.0.0.1 on purpose: on Windows, `localhost` may resolve to ::1 first
  // and WSL2/docker port proxies are IPv4-only -> mysterious disconnects.
  databaseUrl: process.env.DATABASE_URL || "postgres://battery:battery@127.0.0.1:55432/battery",
  adminKey: process.env.ADMIN_KEY || "",
  rateLimitEnabled: process.env.RATE_LIMIT_ENABLED !== "false",

  // Optional: redis://... shares rate-limit counters across instances.
  // Empty = per-process in-memory buckets (fine for single-instance hosts).
  redisUrl: process.env.REDIS_URL || "",
  auditFile:
    process.env.AUDIT_FILE || require("path").join(__dirname, "..", "logs", "audit.log"),

  // Mirrors worker.js constants exactly so clients behave identically.
  rateWindowSec: 60,
  userRateMax: 30,        // requests/min/user (THIEF_ALERT exempt)
  registerRateMax: 10,    // registrations/min/IP
  adminLoginMax: 5,       // failed admin logins/min/IP
  pairLinkMax: 10,        // pair-link attempts/min/IP (brute shield)
  thiefIpMax: 120,        // THIEF_ALERT per IP per minute (generous ceiling)
  authFailLimit: 50,      // failed bearer lookups/hour/token-hash -> denied
  sessionTtlSec: 3600,    // admin session lifetime
  pairTtlSec: 300,        // pairing code lifetime
  maxEventsPerUser: 200,  // bounded per-user event log

  // Incident kill switch: "1" answers 503 on /api/* (health/admin stay up).
  maintenance: process.env.MAINTENANCE_MODE === "1",
};
