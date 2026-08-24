// Shared helpers -- parity with the CF Worker's crypto/rate-limit behavior.

const crypto = require("crypto");
const config = require("./config");

function sha256(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

function randomToken() {
  return crypto.randomBytes(24).toString("hex"); // 48 hex chars, same as worker.js
}

function now() {
  return Math.floor(Date.now() / 1000);
}

function clientIp(req) {
  return req.headers["cf-connecting-ip"] || req.ip || "unknown";
}

// ---- In-memory sliding-window buckets (per server instance) ----
// Same model as worker.js. For multi-instance deployments swap this module
// for a Redis-backed implementation; nothing else needs to change.
const buckets = new Map();

function checkRateLimit(key, max = config.userRateMax) {
  const t = now();
  const bucket = buckets.get(key);
  if (!bucket || t - bucket.window_start > config.rateWindowSec) {
    buckets.set(key, { window_start: t, count: 1 });
    return true;
  }
  bucket.count++;
  return bucket.count <= max;
}

function resetBucket(key) {
  buckets.delete(key);
}

function cleanBuckets() {
  const t = now();
  for (const [key, bucket] of buckets) {
    if (t - bucket.window_start > config.rateWindowSec * 2) buckets.delete(key);
  }
}

module.exports = { sha256, randomToken, now, clientIp, checkRateLimit, resetBucket, cleanBuckets };
