// Battery Notifier Cloud Relay - Cloudflare Worker
// D1-backed relay for 10k-50k users with token auth, rate limiting, admin dashboard
// Deploy on a throwaway domain for security-through-obscurity

const AUTH_PREFIX = "Bearer ";
const RATE_LIMIT_WINDOW = 60; // seconds
const RATE_LIMIT_MAX = 30; // requests per minute per user
const REGISTER_RATE_MAX = 10; // registrations per minute per IP
const ADMIN_LOGIN_MAX = 5; // failed admin logins per minute per IP
const PAIR_LINK_MAX = 10; // pair-link attempts per minute per IP (6-digit brute shield)
const THIEF_IP_MAX = 120; // thief alerts per minute per IP (generous; still bounded)
const PASS_MAX = 5; // disarm-pass attempts per minute per account (brute shield)
const AUTH_FAIL_LIMIT = 50; // failed bearer lookups per hour per token-hash -> deny
const MAX_BODY_BYTES = 16384; // reject oversized bodies before parsing
const ADMIN_SESSION_TTL = 3600; // 1 hour
const MAX_EVENTS_PER_USER = 200; // keep event log bounded
// v2.1 intruder snapshots: the decoded image cap and the JSON-body cap for
// /api/snapshot only (base64 inflates ~4/3, so the body limit is decoded cap
// * 4/3 plus slack for the JSON wrapper).
const SNAPSHOT_MAX_BYTES = 153600; // 150 KB decoded
const SNAPSHOT_BODY_LIMIT = 212992; // 208 KB of base64-in-JSON
const MAX_SNAPSHOTS_PER_USER = 5; // older snapshots get pruned on upload

// Self-hosted users can disable rate limiting via env var
// THIEF_ALERT always bypasses rate limiting regardless of this setting
function isRateLimitEnabled(env) {
  return env.RATE_LIMIT_ENABLED !== "false";
}

// ---- Crypto helpers (Web Crypto API, available in Workers runtime) ----

async function sha256(text) {
  const buf = new TextEncoder().encode(text);
  const hash = await crypto.subtle.digest("SHA-256", buf);
  return [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, "0")).join("");
}

function randomToken() {
  const arr = new Uint8Array(24);
  crypto.getRandomValues(arr);
  return [...arr].map(b => b.toString(16).padStart(2, "0")).join("");
}

// Crypto-random 6-digit code. Math.random() would be predictable to an
// attacker watching the minute window; rejection sampling kills modulo bias.
function sixDigitCode() {
  const max = 900000;
  const limit = Math.floor(4294967296 / max) * max;
  const buf = new Uint32Array(1);
  let v;
  do { crypto.getRandomValues(buf); v = buf[0]; } while (v >= limit);
  return String(100000 + (v % max));
}

function now() { return Math.floor(Date.now() / 1000); }

// ---- Daily aggregate stats (privacy-first: events, never people) ----

const STATS_LOOKBACK_DAYS = 7;
let statsRolledDay = "";

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

function dayOffset(iso, delta) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

// Recompute counters for young days from their source tables. A day's row is
// finalized (computed=1) the first time it is no longer "today" -- after that
// event trimming cannot rewrite history. Today stays open all day.
async function ensureDailyStats(db, force = false) {
  const today = todayStr();
  if (!force && statsRolledDay === today) return;
  try {
    const days = [];
    for (let i = 0; i < STATS_LOOKBACK_DAYS; i++) days.push(dayOffset(today, -i));

    const placeholders = days.map(() => "(?)").join(",");
    await db.prepare(
      `INSERT OR IGNORE INTO daily_stats (day) VALUES ${placeholders}`
    ).bind(...days).run();

    await db.prepare(
      `UPDATE daily_stats SET
         registrations  = (SELECT COUNT(*) FROM users WHERE date(created_at, 'unixepoch') = daily_stats.day),
         alerts         = (SELECT COUNT(*) FROM events WHERE date(ts, 'unixepoch') = daily_stats.day),
         thief_alerts   = (SELECT COUNT(*) FROM events WHERE date(ts, 'unixepoch') = daily_stats.day AND event_type = 'THIEF_ALERT'),
         active_devices = CASE WHEN daily_stats.day = ? THEN
                            (SELECT COUNT(*) FROM users WHERE last_seen > ?)
                          ELSE active_devices END,
         computed       = CASE WHEN daily_stats.day = ? THEN 0 ELSE 1 END
       WHERE day IN (${placeholders}) AND computed = 0`
    ).bind(today, now() - 86400, today, ...days).run();

    statsRolledDay = today;
  } catch (e) {
    // Stats must never break the request path.
    console.error("daily_stats rollup failed:", e.message);
  }
}

// ---- Rate limiting (in-memory, per-worker-instance) ----

const rateBuckets = new Map();

function checkRateLimit(key, max = RATE_LIMIT_MAX) {
  const t = now();
  const bucket = rateBuckets.get(key);
  if (!bucket || t - bucket.window_start > RATE_LIMIT_WINDOW) {
    rateBuckets.set(key, { window_start: t, count: 1 });
    return true;
  }
  bucket.count++;
  return bucket.count <= max;
}

function clientIp(request) {
  return request.headers.get("CF-Connecting-IP") || "unknown";
}

// Clean stale rate buckets periodically (avoid memory bloat)
function cleanRateBuckets() {
  const t = now();
  for (const [key, bucket] of rateBuckets) {
    if (t - bucket.window_start > RATE_LIMIT_WINDOW * 2) {
      rateBuckets.delete(key);
    }
  }
}

// ---- Rogue-token containment --------------------------------------------
// Tokens that rack up >= AUTH_FAIL_LIMIT failed lookups in an hour get
// answered from an in-memory deny-set: instant 403, zero DB hits.

const authFails = new Map();   // tokenHash -> { count, windowStart }
const deniedTokens = new Set();

function noteAuthFail(tokenHash) {
  const t = now();
  let f = authFails.get(tokenHash);
  if (!f || t - f.windowStart > 3600) {
    f = { count: 0, windowStart: t };
    authFails.set(tokenHash, f);
  }
  f.count++;
  if (f.count >= AUTH_FAIL_LIMIT) {
    deniedTokens.add(tokenHash);
    console.warn("rogue token contained:", tokenHash.slice(0, 12));
  }
}

// Clean expired admin sessions from D1 (called periodically on alert)
async function cleanExpiredSessions(db) {
  try {
    await db.prepare("DELETE FROM admin_sessions WHERE expires_at < ?").bind(now()).run();
  } catch (e) {
    // Non-critical, ignore
  }
}

// ---- Response helpers ----

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
    },
  });
}

function html(content, status = 200) {
  return new Response(content, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "X-Frame-Options": "DENY",
    },
  });
}

// ---- Auth: extract token from Authorization header ----

async function authUser(request, db) {
  const authHeader = request.headers.get("Authorization") || "";
  if (!authHeader.startsWith(AUTH_PREFIX)) return null;
  const rawToken = authHeader.slice(AUTH_PREFIX.length).trim();
  if (!rawToken || rawToken.length < 16) return null;
  // Tokens are stored only as sha256 hashes (users.token, users.linked_token).
  const tokenHash = await sha256(rawToken);
  if (deniedTokens.has(tokenHash)) return "denied";
  // Don't filter is_banned in SQL — return "banned" so the client gets a clear error
  const user = await db.prepare("SELECT * FROM users WHERE token = ? OR linked_token = ?")
    .bind(tokenHash, tokenHash).first();
  if (!user) {
    noteAuthFail(tokenHash);
    return null;
  }
  if (user.is_banned) return "banned";
  return user;
}

// ---- Admin auth: session key derived from ADMIN_KEY env var ----

async function adminAuth(request, db) {
  const authHeader = request.headers.get("Authorization") || "";
  const key = authHeader.replace(AUTH_PREFIX, "").trim();
  if (!key) return false;
  // Look up the session key directly — handleAdminLogin stores it already hashed
  const session = await db.prepare("SELECT * FROM admin_sessions WHERE session_key = ? AND expires_at > ?")
    .bind(key, now()).first();
  return !!session;
}

// ---- Route handlers ----

async function handleRegister(request, db, env) {
  // Per-IP throttle: once the URL is public, D1 would otherwise fill with junk rows
  if (isRateLimitEnabled(env) && !checkRateLimit("reg:" + clientIp(request), REGISTER_RATE_MAX)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }
  ensureDailyStats(db);
  const body = await request.json().catch(() => ({}));
  const deviceName = (body.device_name || "").slice(0, 100);
  const platform = (body.platform || "").slice(0, 50);
  const token = randomToken();
  const t = now();

  // Store ONLY the sha256 hash; plaintext is returned to the client exactly once
  const result = await db.prepare(
    "INSERT INTO users (token, device_name, platform, created_at, last_seen) VALUES (?, ?, ?, ?, ?)"
  ).bind(await sha256(token), deviceName, platform, t, t).run();

  return json({ ok: true, token, user_id: result.meta.last_row_id });
}

async function handlePing(request, db, user) {
  const t = now();
  await db.prepare("UPDATE users SET last_seen = ? WHERE user_id = ?").bind(t, user.user_id).run();
  return json({ ok: true, server_time: t });
}

async function handleSendAlert(request, db, user, env, ctx) {
  const body = await request.json().catch(() => ({}));
  // trim matters: "THIEF_ALERT " with trailing space would otherwise lose
  // its rate-limit bypass and get stored as a different type
  const alertType = (body.alert_type || "BATTERY").trim().toUpperCase().slice(0, 20);

  // CRITICAL: Never rate-limit THIEF_ALERT by *user*. A thief unplugging the
  // phone must get through immediately. It still consumes a generous per-IP
  // bucket (120/min) so a rogue token can't burn unlimited CPU/D1.
  const isCriticalAlert = alertType === "THIEF_ALERT";
  if (isCriticalAlert) {
    if (!checkRateLimit("thiefip:" + clientIp(request), THIEF_IP_MAX)) {
      return json({ ok: false, error: "rate_limited" }, 429);
    }
  } else if (isRateLimitEnabled(env) && !checkRateLimit(user.user_id)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }
  cleanRateBuckets();
  await cleanExpiredSessions(db);
  ensureDailyStats(db);
  const batteryPct = typeof body.battery_pct === "number" ? body.battery_pct : -1;
  const isCharging = body.is_charging ? 1 : 0;
  // Optional link to an uploaded intruder snapshot; must belong to this
  // account or the alert is rejected.
  let snapshotId = null;
  if (Number.isInteger(body.snapshot_id) && body.snapshot_id > 0) {
    const owned = await db.prepare(
      "SELECT snap_id FROM snapshots WHERE snap_id = ? AND user_id = ?"
    ).bind(body.snapshot_id, user.user_id).first();
    if (!owned) return json({ ok: false, error: "unknown_snapshot" }, 400);
    snapshotId = body.snapshot_id;
  }
  const t = now();

  await db.prepare(
    "UPDATE users SET alert_active = 1, alert_type = ?, alert_ts = ?, battery_pct = ?, is_charging = ?, total_alerts = total_alerts + 1, last_seen = ? WHERE user_id = ?"
  ).bind(alertType, t, batteryPct, isCharging, t, user.user_id).run();

  // Log event (bounded)
  await db.prepare(
    "INSERT INTO events (user_id, event_type, payload, ts) VALUES (?, ?, ?, ?)"
  ).bind(user.user_id, alertType, JSON.stringify({ battery_pct: batteryPct, charging: isCharging, snapshot_id: snapshotId }), t).run();

  // Trim old events (only if count exceeds limit — avoids heavy subquery on every alert)
  const eventCount = await db.prepare("SELECT COUNT(*) as cnt FROM events WHERE user_id = ?").bind(user.user_id).first();
  if (eventCount.cnt > MAX_EVENTS_PER_USER) {
    const excess = eventCount.cnt - MAX_EVENTS_PER_USER;
    await db.prepare(
      "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE user_id = ? ORDER BY event_id ASC LIMIT ?)"
    ).bind(user.user_id, excess).run();
  }

  // NOTE (v2.0): the old worker-wide Telegram push block was REMOVED.
  // It spammed the owner chat with every user's alerts and leaked device
  // names at scale. Each client now delivers its own notifications via
  // battery_notifier/notifier.py (personal Telegram/email/desktop channels);
  // this worker is a pure relay: store state, hand it back on poll.

  // Opt-in Telegram DM to the owner's own bot -- only on the critical alert,
  // only for accounts that set it up, and never blocking the response.
  if (alertType === "THIEF_ALERT" && ctx) {
    ctx.waitUntil(sendTelegramNotify(env, db, user, snapshotId));
  }

  return json({ ok: true, alert_active: 1, alert_type: alertType, snapshot_id: snapshotId });
}

async function handleClearAlert(request, db, user) {
  await db.prepare(
    "UPDATE users SET alert_active = 0, alert_type = '', last_seen = ? WHERE user_id = ?"
  ).bind(now(), user.user_id).run();
  return json({ ok: true, alert_active: 0 });
}

async function handlePoll(request, db, user) {
  // User polls their own state (laptop checks if phone sent alert).
  // Latest snapshot rides along so the poller can pull the photo.
  const snap = await db.prepare(
    "SELECT snap_id FROM snapshots WHERE user_id = ? ORDER BY snap_id DESC LIMIT 1"
  ).bind(user.user_id).first();
  return json({
    ok: true,
    alert_active: user.alert_active,
    alert_type: user.alert_type || "",
    alert_ts: user.alert_ts,
    battery_pct: user.battery_pct,
    is_charging: user.is_charging,
    snapshot_id: snap ? snap.snap_id : null,
    snapshot_url: snap ? `/api/snapshot/${snap.snap_id}` : null,
    // v2.3: account-level armed state, so any device can see/act on it
    armed: user.armed ? 1 : 0,
    armed_by: user.armed_by || null,
    has_pass: !!user.disarm_hash,
  });
}

// ---- v2.3: account-level arm/disarm + disarm pass ------------------------
// The pass is the second factor for the dangerous direction: arming is free,
// disarming (from any device) needs it. Only the sha256 lands in D1.

async function handlePassSetup(request, db, user) {
  const body = await request.json().catch(() => ({}));
  const pass = (body.pass_code || "").trim();
  const current = (body.current_pass_code || "").trim();
  if (!pass || pass.length < 4 || pass.length > 64) {
    return json({ ok: false, error: "invalid_pass" }, 400);
  }
  if (user.disarm_hash) {
    if (!current) return json({ ok: false, error: "current_pass_required" }, 401);
    if (await sha256(current) !== user.disarm_hash) {
      return json({ ok: false, error: "invalid_pass" }, 401);
    }
  }
  await db.prepare("UPDATE users SET disarm_hash = ? WHERE user_id = ?")
    .bind(await sha256(pass), user.user_id).run();
  return json({ ok: true });
}

async function handleArm(request, db, user, env) {
  // Brute shield on the pass: 5 attempts/min per account. Arming without a
  // pass also consumes a slot? No -- only pass-carrying attempts count.
  const body = await request.json().catch(() => ({}));
  const wantArmed = body.armed ? 1 : 0;
  const pass = (body.pass_code || "").trim();

  if (!wantArmed && user.disarm_hash) {
    if (isRateLimitEnabled(env) && !checkRateLimit("pass:" + user.user_id, PASS_MAX)) {
      return json({ ok: false, error: "rate_limited" }, 429);
    }
    if (!pass) return json({ ok: false, error: "pass_required" }, 401);
    if (await sha256(pass) !== user.disarm_hash) {
      return json({ ok: false, error: "invalid_pass" }, 401);
    }
  }
  await db.prepare(
    "UPDATE users SET armed = ?, armed_by = ?, last_seen = ? WHERE user_id = ?"
  ).bind(wantArmed, user.device_name || "device", now(), user.user_id).run();
  return json({ ok: true, armed: wantArmed });
}

// ---- v2.1: intruder snapshots -------------------------------------------
// Laptop uploads one webcam frame on a failed logon while armed; any device
// holding the account's token (laptop or paired phone) can fetch it back.

// Look at the leading bytes, not the filename -- anything else would let a
// client store text/scripts with an image content type.
function sniffImage(bytes) {
  if (bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) {
    return "image/jpeg";
  }
  if (bytes.length > 8 && bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) {
    return "image/png";
  }
  return null;
}

function base64ToBytes(b64) {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes;
}

async function handleSnapshotUpload(request, db, env, user) {
  if (!env.SNAPSHOTS) return json({ ok: false, error: "snapshots_not_configured" }, 501);
  // Snapshots are rare by design; a tighter bucket than /api/alert keeps one
  // token from filling the R2 bucket.
  if (isRateLimitEnabled(env) && !checkRateLimit("snap:" + user.user_id, 10)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }
  const body = await request.json().catch(() => ({}));
  const b64 = typeof body.image === "string" ? body.image : "";
  if (!b64 || b64.length > SNAPSHOT_BODY_LIMIT) {
    return json({ ok: false, error: "bad_image" }, 400);
  }
  let bytes;
  try {
    bytes = base64ToBytes(b64);
  } catch (_) {
    return json({ ok: false, error: "bad_image" }, 400);
  }
  if (bytes.length === 0 || bytes.length > SNAPSHOT_MAX_BYTES) {
    return json({ ok: false, error: "bad_image" }, 400);
  }
  const contentType = sniffImage(bytes);
  if (!contentType) return json({ ok: false, error: "unsupported_format" }, 415);

  const t = now();
  const r2Key = `snap/${user.user_id}/${t}-${randomToken().slice(0, 8)}`;
  await env.SNAPSHOTS.put(r2Key, bytes, { httpMetadata: { contentType } });
  const result = await db.prepare(
    "INSERT INTO snapshots (user_id, r2_key, content_type, bytes, created_at) VALUES (?, ?, ?, ?, ?)"
  ).bind(user.user_id, r2Key, contentType, bytes.length, t).run();

  // Retention: only the newest MAX_SNAPSHOTS_PER_USER survive; prune the rest
  // from R2 too so the bucket can't grow behind the D1 trim.
  const stale = await db.prepare(
    "SELECT snap_id, r2_key FROM snapshots WHERE user_id = ? ORDER BY snap_id DESC LIMIT -1 OFFSET ?"
  ).bind(user.user_id, MAX_SNAPSHOTS_PER_USER).all();
  for (const row of stale.results || []) {
    try { await env.SNAPSHOTS.delete(row.r2_key); } catch (_) {}
    await db.prepare("DELETE FROM snapshots WHERE snap_id = ?").bind(row.snap_id).run();
  }

  return json({ ok: true, snap_id: result.meta.last_row_id, bytes: bytes.length });
}

async function handleSnapshotFetch(request, db, env, user, snapId) {
  if (!env.SNAPSHOTS) return json({ ok: false, error: "snapshots_not_configured" }, 501);
  // Ownership check: a paired phone shares the account, a stranger's token doesn't.
  const row = await db.prepare(
    "SELECT r2_key, content_type FROM snapshots WHERE snap_id = ? AND user_id = ?"
  ).bind(snapId, user.user_id).first();
  if (!row) return json({ ok: false, error: "not_found" }, 404);
  const obj = await env.SNAPSHOTS.get(row.r2_key);
  if (!obj) return json({ ok: false, error: "not_found" }, 404);
  return new Response(obj.body, {
    headers: {
      "Content-Type": row.content_type || "application/octet-stream",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    },
  });
}

// ---- v2.2: per-account opt-in Telegram delivery --------------------------
// The stored bot token + chat id belong to the account owner themselves;
// the worker only ever messages that one chat, and only on THIEF_ALERT.
// Accounts that never call /api/notify/setup keep the pure-relay behavior.

async function handleNotifySetup(request, db, user) {
  const body = await request.json().catch(() => ({}));
  const botToken = (body.bot_token || "").trim();
  const chatId = (body.chat_id || "").trim();
  // Bot tokens look like 1234567890:AAex...; chat ids numeric or @channelname
  if (!/^\d{8,12}:[\w-]{30,}$/.test(botToken)) {
    return json({ ok: false, error: "invalid_bot_token" }, 400);
  }
  if (!/^(-?\d{5,20}|@[\w]{4,64})$/.test(chatId)) {
    return json({ ok: false, error: "invalid_chat_id" }, 400);
  }
  await db.prepare(
    "INSERT INTO user_notify (user_id, bot_token, chat_id, created_at) VALUES (?, ?, ?, ?) " +
    "ON CONFLICT(user_id) DO UPDATE SET bot_token = excluded.bot_token, chat_id = excluded.chat_id"
  ).bind(user.user_id, botToken, chatId, now()).run();
  return json({ ok: true });
}

async function handleNotifyClear(request, db, user) {
  await db.prepare("DELETE FROM user_notify WHERE user_id = ?").bind(user.user_id).run();
  return json({ ok: true });
}

async function telegramApi(botToken, method, payload) {
  const isForm = payload instanceof FormData;
  const resp = await fetch(`https://api.telegram.org/bot${botToken}/${method}`, {
    method: "POST",
    headers: isForm ? undefined : { "Content-Type": "application/json" },
    body: isForm ? payload : JSON.stringify(payload),
  });
  return resp.json().catch(() => ({}));
}

// Fire-and-forget via ctx.waitUntil: a Telegram outage must never delay or
// fail the relayed alert.
async function sendTelegramNotify(env, db, user, snapshotId) {
  try {
    const prefs = await db.prepare(
      "SELECT bot_token, chat_id FROM user_notify WHERE user_id = ?"
    ).bind(user.user_id).first();
    if (!prefs) return;

    let sent = null;
    if (snapshotId && env.SNAPSHOTS) {
      const row = await db.prepare(
        "SELECT r2_key FROM snapshots WHERE snap_id = ? AND user_id = ?"
      ).bind(snapshotId, user.user_id).first();
      const obj = row ? await env.SNAPSHOTS.get(row.r2_key) : null;
      if (obj) {
        const form = new FormData();
        form.append("chat_id", prefs.chat_id);
        form.append("caption", `Intruder Guard: ${user.device_name || "laptop"} raised THIEF_ALERT`);
        form.append("photo", new Blob([await obj.arrayBuffer()],
          { type: obj.httpMetadata?.contentType || "image/jpeg" }), "intruder.jpg");
        sent = await telegramApi(prefs.bot_token, "sendPhoto", form);
      }
    }
    if (!sent || !sent.ok) {
      sent = await telegramApi(prefs.bot_token, "sendMessage", {
        chat_id: prefs.chat_id,
        text: `THIEF_ALERT from ${user.device_name || "your device"}` +
              (snapshotId ? ` (snapshot ${snapshotId})` : ""),
      });
    }
    if (!sent.ok) console.error("telegram notify failed:", sent.description);
  } catch (e) {
    console.error("telegram notify error:", e.message);
  }
}

// ---- Admin endpoints ----

async function handleAdminLogin(request, db, env) {
  // Guard: if ADMIN_KEY secret is not configured, don't allow login
  if (!env.ADMIN_KEY || env.ADMIN_KEY.length < 10) {
    return json({ ok: false, error: "admin_key_not_configured" }, 500);
  }
  // Brute-force guard: max failed logins per IP per minute
  const ip = clientIp(request);
  if (!checkRateLimit("alogin:" + ip, ADMIN_LOGIN_MAX)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }
  const body = await request.json().catch(() => ({}));
  const adminKey = body.admin_key || "";
  if (!adminKey || adminKey.length < 10) {
    return json({ ok: false, error: "invalid_key" }, 401);
  }
  const expectedHash = await sha256(env.ADMIN_KEY + "admin_salt");
  const providedHash = await sha256(adminKey + "admin_salt");
  if (expectedHash !== providedHash) {
    return json({ ok: false, error: "invalid_key" }, 401);
  }
  rateBuckets.delete("alogin:" + ip); // success resets the failure counter
  const sessionKey = await sha256(randomToken() + adminKey);
  const t = now();
  await db.prepare(
    "INSERT OR REPLACE INTO admin_sessions (session_key, created_at, expires_at) VALUES (?, ?, ?)"
  ).bind(sessionKey, t, t + ADMIN_SESSION_TTL).run();
  return json({ ok: true, session_key: sessionKey, expires_in: ADMIN_SESSION_TTL });
}

async function handleAdminStats(db) {
  await ensureDailyStats(db, true);
  const total = await db.prepare("SELECT COUNT(*) as cnt FROM users").first();
  const active = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE last_seen > ?").bind(now() - 300).first();
  const alerts = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE alert_active = 1").first();
  const banned = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1").first();
  const pro = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_pro = 1").first();
  const founding = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_founding = 1").first();
  const totalAlerts = await db.prepare("SELECT SUM(total_alerts) as cnt FROM users").first();
  const recentUsers = await db.prepare("SELECT user_id, device_name, platform, last_seen, is_banned, alert_active, alert_type, alert_ts, battery_pct, is_charging, total_alerts, is_pro, is_founding FROM users ORDER BY last_seen DESC LIMIT 50").all();
  const daily = await db.prepare("SELECT * FROM daily_stats ORDER BY day DESC LIMIT 30").all();
  return json({
    ok: true,
    stats: {
      total_users: total.cnt,
      active_5min: active.cnt,
      active_alerts: alerts.cnt,
      banned: banned.cnt,
      pro: pro.cnt,
      founding: founding.cnt,
      total_alerts_sent: totalAlerts.cnt || 0,
    },
    recent_users: recentUsers.results || [],
    daily: daily.results || [],
  });
}

async function handleAdminBan(request, db) {
  const body = await request.json().catch(() => ({}));
  const userId = body.user_id;
  if (!userId) return json({ ok: false, error: "missing user_id" }, 400);
  await db.prepare("UPDATE users SET is_banned = 1 WHERE user_id = ?").bind(userId).run();
  return json({ ok: true, banned: userId });
}

async function handleAdminUnban(request, db) {
  const body = await request.json().catch(() => ({}));
  const userId = body.user_id;
  if (!userId) return json({ ok: false, error: "missing user_id" }, 400);
  await db.prepare("UPDATE users SET is_banned = 0 WHERE user_id = ?").bind(userId).run();
  return json({ ok: true, unbanned: userId });
}

async function handleAdminBroadcast(request, db) {
  // Force-set alert for all users (e.g., emergency test)
  const body = await request.json().catch(() => ({}));
  const alertType = (body.alert_type || "TEST").toUpperCase().slice(0, 20);
  const t = now();
  await db.prepare("UPDATE users SET alert_active = 1, alert_type = ?, alert_ts = ? WHERE is_banned = 0").bind(alertType, t).run();
  return json({ ok: true, broadcast: alertType });
}

async function handleAdminClearAll(db) {
  await db.prepare("UPDATE users SET alert_active = 0, alert_type = ''").run();
  return json({ ok: true, cleared: true });
}

// ---- HTML Dashboard ----

// Escape user-controlled values before interpolating into the dashboard.
// device_name/platform come straight from unauthenticated /api/register.
function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Tiny inline SVG sparkline of alerts/day -- no dependencies.
function dailySparkline(daily) {
  const rows = (daily || []).slice().reverse(); // oldest -> newest
  if (!rows.length) return "";
  const max = Math.max(1, ...rows.map(r => r.alerts || 0));
  const w = 280, h = 56;
  const pts = rows.map((r, i) => {
    const x = (i / Math.max(1, rows.length - 1)) * (w - 4) + 2;
    const y = h - 4 - ((r.alerts || 0) / max) * (h - 10);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const todayRow = rows[rows.length - 1];
  return `<div class="stat-card" style="grid-column: 1 / -1;">
    <div class="label">Alerts per day (aggregate only)</div>
    <svg width="${w}" height="${h}" style="display:block;margin-top:6px">
      <polyline fill="none" stroke="#00d4ff" stroke-width="2" points="${pts}"/>
    </svg>
    <div class="label">${todayRow.day}: ${todayRow.alerts ?? "-"} alerts · ${todayRow.registrations ?? "-"} new devices · ${todayRow.active_devices ?? "-"} active · ${todayRow.pairings ?? 0} pairings</div>
  </div>`;
}

function dashboardHTML(data) {
  const s = data.stats;
  const rows = (data.recent_users || []).map(u => {
    const uid = escapeHtml(u.user_id);
    return `
    <tr>
      <td>${uid}</td>
      <td>${escapeHtml(u.device_name || '-')}</td>
      <td>${escapeHtml(u.platform || '-')}</td>
      <td>${u.alert_active ? '<span class="alert">ACTIVE</span>' : 'idle'}</td>
      <td>${escapeHtml(u.alert_type || '-')}</td>
      <td>${u.battery_pct >= 0 ? u.battery_pct + '%' : '-'}</td>
      <td>${u.is_charging ? 'charging' : '-'}</td>
      <td>${Number(u.total_alerts) || 0}</td>
      <td>${u.is_banned ? 'BANNED' : (u.is_pro ? 'PRO' : (u.is_founding ? 'FOUNDING' : 'free'))}</td>
      <td><button class="ban-btn" data-uid="${uid}">ban</button></td>
    </tr>`;
  }).join("");

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'">
<title>Battery Relay Admin</title>
<style>
  body { font-family: monospace; background: #1a1a2e; color: #e0e0e0; margin: 20px; }
  h1 { color: #00d4ff; } h2 { color: #ff9f43; margin-top: 30px; }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; margin: 20px 0; }
  .stat-card { background: #16213e; padding: 16px; border-radius: 8px; border: 1px solid #30475e; }
  .stat-card .label { color: #888; font-size: 12px; text-transform: uppercase; }
  .stat-card .value { font-size: 28px; font-weight: bold; color: #00d4ff; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #30475e; padding: 6px 10px; text-align: left; }
  th { background: #16213e; color: #00d4ff; }
  tr:nth-child(even) { background: #16213e; }
  .alert { color: #ff4757; font-weight: bold; }
  .ban-btn { background: #ff4757; color: white; border: none; padding: 3px 8px; border-radius: 4px; cursor: pointer; font-size: 11px; }
  .ban-btn:hover { background: #c0392b; }
  .actions { margin: 20px 0; }
  .actions button { margin-right: 10px; padding: 8px 16px; background: #30475e; color: white; border: none; border-radius: 4px; cursor: pointer; }
  .actions button:hover { background: #00d4ff; color: #1a1a2e; }
</style>
</head><body>
<h1>Battery Relay Admin Dashboard</h1>
<div class="stat-grid">
  <div class="stat-card"><div class="label">Total Users</div><div class="value">${s.total_users}</div></div>
  <div class="stat-card"><div class="label">Active (5min)</div><div class="value">${s.active_5min}</div></div>
  <div class="stat-card"><div class="label">Active Alerts</div><div class="value">${s.active_alerts}</div></div>
  <div class="stat-card"><div class="label">Total Alerts Sent</div><div class="value">${s.total_alerts_sent}</div></div>
  <div class="stat-card"><div class="label">Pro Users</div><div class="value">${s.pro}</div></div>
  <div class="stat-card"><div class="label">Founding</div><div class="value">${s.founding}</div></div>
  <div class="stat-card"><div class="label">Banned</div><div class="value">${s.banned}</div></div>
  ${dailySparkline(data.daily)}
</div>
<div class="actions">
  <button onclick="fetch('/admin/broadcast',{method:'POST',headers:{'Authorization':'Bearer '+localStorage.getItem('sk')},body:JSON.stringify({alert_type:'TEST'})}).then(()=>location.reload())">Broadcast Test Alert</button>
  <button onclick="fetch('/admin/clear-all',{method:'POST',headers:{'Authorization':'Bearer '+localStorage.getItem('sk')}}).then(()=>location.reload())">Clear All Alerts</button>
  <button onclick="location.reload()">Refresh</button>
</div>
<h2>Recent Users (last 50)</h2>
<table>
  <tr><th>ID</th><th>Device</th><th>Platform</th><th>Alert</th><th>Type</th><th>Battery</th><th>Charging</th><th>Total Alerts</th><th>Plan</th><th>Action</th></tr>
  ${rows}
</table>
<script>
  document.querySelectorAll('.ban-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const uid = btn.dataset.uid;
      fetch('/admin/ban', {method:'POST',headers:{'Authorization':'Bearer '+localStorage.getItem('sk'),'Content-Type':'application/json'},body:JSON.stringify({user_id:parseInt(uid)})}).then(()=>location.reload());
    });
  });
</script>
</body></html>`;
}

async function handleAdminDashboard(request, db) {
  const authHeader = request.headers.get("Authorization") || "";
  const isAuthed = await adminAuth(request, db);
  if (!isAuthed) {
    // If the request carries a Bearer token that failed, return 401
    // so the frontend can detect token expiry and clear localStorage
    if (authHeader.startsWith(AUTH_PREFIX)) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }
    return html(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Admin Login</title>
<style>body{font-family:monospace;background:#1a1a2e;color:#e0e0e0;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
input{padding:12px;width:300px;font-size:16px;background:#16213e;color:#e0e0e0;border:1px solid #30475e;border-radius:4px}
button{padding:12px 24px;font-size:16px;background:#00d4ff;color:#1a1a2e;border:none;border-radius:4px;cursor:pointer;margin-top:10px}
</style></head><body>
<div><h2>Admin Login</h2>
<input id="key" type="password" placeholder="Admin key" onkeydown="if(event.key==='Enter')login()"><br>
<button onclick="login()">Login</button></div>
<script>
// 1. Check if we already have a session key saved from a successful login
const sk = localStorage.getItem('sk');
if (sk) {
  fetch('/admin', { headers: { 'Authorization': 'Bearer ' + sk } })
  .then(r => {
    if (r.ok) { r.text().then(html => { document.open(); document.write(html); document.close(); }); }
    else { localStorage.removeItem('sk'); } // Key expired or invalid, clear it
  });
}

// 2. The standard login function
function login(){
  fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({admin_key:document.getElementById('key').value})})
  .then(r=>r.json()).then(d=>{if(d.ok){localStorage.setItem('sk',d.session_key);location.reload()}else{alert('Invalid key')}});
}
</script>
</body></html>`);
  }
  const statsData = await handleAdminStats(db);
  const data = await statsData.json();
  return html(dashboardHTML(data));
}
// ---- Pairing System ----

async function handlePairGenerate(request, db, user) {
  // Generate a crypto-random 6-digit string
  const code = sixDigitCode();
  const expiresAt = now() + 300; // 5 minutes from now

  // Store the owning user's id only -- no tokens are ever stored in plaintext
  await db.prepare("INSERT INTO pairing_codes (code, user_id, expires_at) VALUES (?, ?, ?)")
    .bind(code, user.user_id, expiresAt).run();

  return json({ ok: true, code: code, expires_in: 300 });
}

async function handlePairLink(request, db) {
  // Brute-force shield: 6 digits = 900k space. In-memory caps are per-isolate
  // and can be spread across CF isolates, so pair-link uses a GLOBAL D1
  // counter per IP per minute. Only attackers generate writes here.
  const ip = clientIp(request);
  const minuteBucket = Math.floor(now() / RATE_LIMIT_WINDOW);
  const pfKey = `${ip}:${minuteBucket}`;
  try {
    await db.prepare(
      `INSERT INTO pair_fails (ip_window, fails, ts) VALUES (?, 1, ?)
       ON CONFLICT (ip_window) DO UPDATE SET fails = fails + 1`
    ).bind(pfKey, now()).run();
    const { results } = await db.prepare(
      "SELECT fails FROM pair_fails WHERE ip_window = ?"
    ).bind(pfKey).all();
    if ((results[0]?.fails || 0) > PAIR_LINK_MAX) {
      return json({ ok: false, error: "rate_limited" }, 429);
    }
  } catch (e) {
    // Shield failure must not break legitimate pairing -- fail open.
    console.error("pair shield error:", e.message);
  }
  const body = await request.json().catch(() => ({}));
  const code = body.code;
  if (!code || code.length !== 6 || !/^\d{6}$/.test(code)) return json({ ok: false, error: "invalid_code" }, 400);

  const record = await db.prepare("SELECT * FROM pairing_codes WHERE code = ? AND expires_at > ?")
    .bind(code, now()).first();

  if (!record) return json({ ok: false, error: "invalid_or_expired" }, 404);

  // Single-use: Delete the code immediately so it can't be reused
  await db.prepare("DELETE FROM pairing_codes WHERE code = ?").bind(code).run();

  // Mint a FRESH linked token for the joining device. Only its sha256 hash is
  // persisted (users.linked_token); the plaintext is returned exactly once.
  // Re-linking rotates the linked token, de-authorizing the previous phone.
  const linkedToken = randomToken();
  await db.prepare("UPDATE users SET linked_token = ?, last_seen = ? WHERE user_id = ?")
    .bind(await sha256(linkedToken), now(), record.user_id).run();

  // Rare event -> inline increment is free; the code row is already deleted
  // so there is nothing to count retroactively.
  await db.prepare(
    "INSERT INTO daily_stats (day, pairings) VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET pairings = pairings + 1"
  ).bind(todayStr()).run();

  return json({ ok: true, token: linkedToken });
}
// ---- Main router ----

export default {
  async fetch(request, env, ctx) {
    const db = env.DB;
    const url = new URL(request.url);
    const path = url.pathname;

    // Incident kill switch: /api/* closes; health + admin stay reachable.
    // NOTE: always drain the request body before an early response --
    // replying without consuming the body stalls the TCP stream.
    if (env.MAINTENANCE_MODE === "1" && path.startsWith("/api/")) {
      try { await request.arrayBuffer(); } catch (_) {}
      return json({ ok: false, error: "maintenance" }, 503);
    }

    // Body-size gate: reject oversized payloads before parsing. We still
    // drain the bytes so the client's send() completes cleanly. Snapshot
    // uploads carry a base64 webcam frame, so they get their own limit.
    const contentLength = parseInt(request.headers.get("Content-Length") || "0", 10);
    const bodyLimit = path === "/api/snapshot" ? SNAPSHOT_BODY_LIMIT : MAX_BODY_BYTES;
    if (contentLength > bodyLimit) {
      try { await request.arrayBuffer(); } catch (_) {}
      return json({ ok: false, error: "payload_too_large" }, 413);
    }

    // Native clients and the same-origin dashboard don't need CORS, so we
    // don't send it: this kills drive-by browser abuse of the public API.
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204 });
    }

    // ---- Public API ----
    if (path === "/api/register" && request.method === "POST") return handleRegister(request, db, env);

    // 6-Digit Pairing System
    if (path === "/api/pair/generate" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handlePairGenerate(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/pair/link" && request.method === "POST") {
      return handlePairLink(request, db);
    }

    if (path === "/api/ping" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handlePing(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/alert" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleSendAlert(request, db, u, env, ctx) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/clear" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleClearAlert(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/poll" && request.method === "GET") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handlePoll(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    // v2.1 intruder snapshots
    if (path === "/api/snapshot" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleSnapshotUpload(request, db, env, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path.startsWith("/api/snapshot/") && request.method === "GET") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      if (!u) return json({ ok: false, error: "unauthorized" }, 401);
      const snapId = parseInt(path.slice("/api/snapshot/".length), 10);
      if (!snapId) return json({ ok: false, error: "not_found" }, 404);
      return handleSnapshotFetch(request, db, env, u, snapId);
    }
    // v2.2 opt-in Telegram delivery
    if (path === "/api/notify/setup" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleNotifySetup(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/notify/clear" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleNotifyClear(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    // v2.3 account-level arm/disarm + disarm pass
    if (path === "/api/pass/setup" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handlePassSetup(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/arm" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      if (u === "denied") return json({ ok: false, error: "denied" }, 403);
      return u ? handleArm(request, db, u, env) : json({ ok: false, error: "unauthorized" }, 401);
    }
    // ---- Admin API ----
    if (path === "/admin/login" && request.method === "POST") return handleAdminLogin(request, db, env);
    if (path === "/admin" || path === "/admin/") {
      return handleAdminDashboard(request, db);
    }
    if (path.startsWith("/admin/")) {
      const isAuthed = await adminAuth(request, db);
      if (!isAuthed) return json({ ok: false, error: "unauthorized" }, 401);
      if (path === "/admin/stats" && request.method === "GET") return handleAdminStats(db);
      if (path === "/admin/ban" && request.method === "POST") return handleAdminBan(request, db);
      if (path === "/admin/unban" && request.method === "POST") return handleAdminUnban(request, db);
      if (path === "/admin/broadcast" && request.method === "POST") return handleAdminBroadcast(request, db);
      if (path === "/admin/clear-all" && request.method === "POST") return handleAdminClearAll(db);
    }

    // ---- Health check (looks like a generic page to obscure the endpoint) ----
    if (path === "/" || path === "/health") {
      return html("<html><body><h1>OK</h1></body></html>");
    }

    // ---- Plain-language privacy page (see SECURITY.md for the full model) ----
    if (path === "/privacy") {
      return html(`<!DOCTYPE html><html><head><meta charset="utf-8"><title>Battery Relay Privacy</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:40px auto;line-height:1.5">
<h1>What this relay stores</h1>
<p>Per device: a <b>hashed</b> auth token, a device name you chose, your platform,
battery percentage, charging state, alert timestamps, and the last 200 alert events.</p>
<p>No accounts, no emails, no phone numbers, no location, no analytics.
Tokens are stored only as SHA-256 hashes. Pairing codes expire after 5 minutes.</p>
<p>The only usage data is aggregate daily counts (how many devices registered,
how many alerts fired) -- individual requests are never tracked or stored by IP.</p>
<p>This server never sends notifications on its own -- your devices deliver their own alerts.</p>
<p><a href="https://github.com/Saman-ghorayshi/battery-music-notifier/blob/main/SECURITY.md">Full security model</a></p>
</body></html>`);
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};
