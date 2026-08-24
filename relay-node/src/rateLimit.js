// Rate limiting: Redis fixed-window counters when REDIS_URL is set,
// in-memory Map otherwise. Same call signature either way, so routes and
// tests don't care which backend is active.
//
// Design notes:
//   * fixed window (INCR + EXPIRE) -- good enough for abuse control, no
//     sliding-window lua scripts needed
//   * fail-open: if redis errors we let the request through. A dead cache
//     must never block a THIEF_ALERT.
const config = require("./config");
const { now } = require("./util");

let redis = null;

async function initRateLimit() {
  if (!config.redisUrl) return;
  const { createClient } = require("redis");
  redis = createClient({ url: config.redisUrl });
  redis.on("error", (err) => console.error("[redis]", err.message));
  await redis.connect();
  console.log(`Rate limiting via redis (${config.redisUrl})`);
}

// ---- in-memory fallback (single instance) ----
const buckets = new Map();

function memoryCheck(key, max) {
  const t = now();
  const bucket = buckets.get(key);
  if (!bucket || t - bucket.window_start > config.rateWindowSec) {
    buckets.set(key, { window_start: t, count: 1 });
    return true;
  }
  bucket.count++;
  return bucket.count <= max;
}

function memoryReset(key) {
  buckets.delete(key);
}

// ---- public API ----

async function checkRateLimit(key, max = config.userRateMax) {
  if (!redis) return memoryCheck(key, max);

  const win = Math.floor(now() / config.rateWindowSec);
  const rk = `rl:${key}:${win}`;
  try {
    const n = await redis.incr(rk);
    if (n === 1) await redis.expire(rk, config.rateWindowSec * 2);
    return n <= max;
  } catch (err) {
    console.error("[redis] rate check failed, failing open:", err.message);
    return true;
  }
}

async function resetBucket(key) {
  if (!redis) return memoryReset(key);
  try {
    // clear every window slice for this key; cheap, rare operation
    const keys = await redis.keys(`rl:${key}:*`);
    if (keys.length) await redis.del(keys);
  } catch (_) { /* best effort */ }
}

// periodic cleanup only matters for the memory backend
setInterval(() => {
  const t = now();
  for (const [key, bucket] of buckets) {
    if (t - bucket.window_start > config.rateWindowSec * 2) buckets.delete(key);
  }
}, config.rateWindowSec * 2000).unref();

module.exports = { initRateLimit, checkRateLimit, resetBucket };
