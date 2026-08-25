// Core client API: register / ping / alert / clear / poll.
// Response shapes match worker.js byte-for-byte so the Python/Termux/Kotlin
// clients work against either backend without changes.
const express = require("express");
const pool = require("../db");
const config = require("../config");
const { sha256, randomToken, now, clientIp } = require("../util");
const { checkRateLimit } = require("../rateLimit");
const { ensureDailyStats } = require("../stats");
const { authUser, purgeExpired } = require("../auth");

const router = express.Router();

// ---- POST /api/register --------------------------------------------------
router.post("/api/register", async (req, res) => {
  if (config.rateLimitEnabled && !(await checkRateLimit("reg:" + clientIp(req), config.registerRateMax))) {
    return res.status(429).json({ ok: false, error: "rate_limited" });
  }
  ensureDailyStats().catch(() => {});
  const body = req.body || {};
  const deviceName = String(body.device_name || "").slice(0, 100);
  const platform = String(body.platform || "").slice(0, 50);
  const token = randomToken();
  const t = now();

  // Store ONLY the sha256 hash; plaintext is returned to the client once.
  const { rows } = await pool.query(
    `INSERT INTO users (token, device_name, platform, created_at, last_seen)
     VALUES ($1, $2, $3, $4, $5)
     RETURNING user_id`,
    [sha256(token), deviceName, platform, t, t],
  );
  res.json({ ok: true, token, user_id: rows[0].user_id });
});

// ---- POST /api/ping ------------------------------------------------------
router.post("/api/ping", authUser, async (req, res) => {
  await pool.query("UPDATE users SET last_seen = $1 WHERE user_id = $2", [now(), req.user.user_id]);
  res.json({ ok: true, server_time: now() });
});

// ---- POST /api/alert -----------------------------------------------------
router.post("/api/alert", authUser, async (req, res) => {
  const body = req.body || {};
  const alertType = String(body.alert_type || "BATTERY").toUpperCase().slice(0, 20);

  // THIEF_ALERT always bypasses rate limiting -- a thief unplugging the
  // charger must get through even if the device has been polling heavily.
  const isCriticalAlert = alertType === "THIEF_ALERT";
  if (!isCriticalAlert && config.rateLimitEnabled && !(await checkRateLimit(req.user.user_id))) {
    return res.status(429).json({ ok: false, error: "rate_limited" });
  }
  purgeExpired(pool);
  ensureDailyStats().catch(() => {});

  const batteryPct = typeof body.battery_pct === "number" ? body.battery_pct : -1;
  const isCharging = body.is_charging ? 1 : 0;
  const t = now();

  await pool.query(
    `UPDATE users SET alert_active = 1, alert_type = $1, alert_ts = $2,
       battery_pct = $3, is_charging = $4, total_alerts = total_alerts + 1,
       last_seen = $2 WHERE user_id = $5`,
    [alertType, t, batteryPct, isCharging, req.user.user_id],
  );

  await pool.query(
    "INSERT INTO events (user_id, event_type, payload, ts) VALUES ($1, $2, $3, $4)",
    [req.user.user_id, alertType, JSON.stringify({ battery_pct: batteryPct, charging: !!isCharging }), t],
  );

  // Trim the event log to MAX_EVENTS_PER_USER (only when over budget).
  const { rows } = await pool.query(
    "SELECT COUNT(*)::int AS cnt FROM events WHERE user_id = $1",
    [req.user.user_id],
  );
  if (rows[0].cnt > config.maxEventsPerUser) {
    const excess = rows[0].cnt - config.maxEventsPerUser;
    await pool.query(
      `DELETE FROM events WHERE event_id IN (
         SELECT event_id FROM events WHERE user_id = $1 ORDER BY event_id ASC LIMIT $2)`,
      [req.user.user_id, excess],
    );
  }

  // NOTE (v2.0): no server-side Telegram push -- each client delivers its own
  // notifications. This worker is a pure relay (same policy as the CF Worker).

  res.json({ ok: true, alert_active: 1, alert_type: alertType });
});

// ---- POST /api/clear -----------------------------------------------------
router.post("/api/clear", authUser, async (req, res) => {
  await pool.query(
    "UPDATE users SET alert_active = 0, alert_type = '', last_seen = $1 WHERE user_id = $2",
    [now(), req.user.user_id],
  );
  res.json({ ok: true, alert_active: 0 });
});

// ---- GET /api/poll -------------------------------------------------------
router.get("/api/poll", authUser, async (req, res) => {
  const u = req.user;
  res.json({
    ok: true,
    alert_active: u.alert_active,
    alert_type: u.alert_type || "",
    alert_ts: u.alert_ts,
    battery_pct: u.battery_pct,
    is_charging: u.is_charging,
  });
});

module.exports = router;
