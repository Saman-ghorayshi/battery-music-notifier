// Admin API: login + stats + ban/unban/broadcast/clear-all.
// Session keys are sha256(randomToken() + adminKey), stored hashed, 1h TTL.
// The Python `battery-music admin` CLI works against these endpoints as-is
// (the HTML dashboard remains a CF-Worker feature; see README roadmap).
const express = require("express");
const pool = require("../db");
const config = require("../config");
const { sha256, randomToken, now, clientIp } = require("../util");
const { checkRateLimit, resetBucket } = require("../rateLimit");
const { adminAuth, purgeExpired } = require("../auth");
const audit = require("../audit");

const router = express.Router();

// ---- POST /admin/login -----------------------------------------------------
router.post("/admin/login", async (req, res) => {
  if (!config.adminKey || config.adminKey.length < 10) {
    return res.status(500).json({ ok: false, error: "admin_key_not_configured" });
  }
  // Brute-force guard: max failed logins per IP per minute (reset on success).
  const ip = clientIp(req);
  if (config.rateLimitEnabled && !(await checkRateLimit("alogin:" + ip, config.adminLoginMax))) {
    return res.status(429).json({ ok: false, error: "rate_limited" });
  }
  const body = req.body || {};
  const provided = String(body.admin_key || "");
  if (provided.length < 10 || provided !== config.adminKey) {
    audit(req, "admin_login_failed", { reason: "bad key" });
    return res.status(401).json({ ok: false, error: "invalid_key" });
  }
  await resetBucket("alogin:" + ip);

  await purgeExpired(pool);
  const sessionKey = sha256(randomToken() + provided);
  const t = now();
  await pool.query(
    `INSERT INTO admin_sessions (session_key, created_at, expires_at)
     VALUES ($1, $2, $3)
     ON CONFLICT (session_key) DO UPDATE SET created_at = EXCLUDED.created_at,
                                              expires_at = EXCLUDED.expires_at`,
    [sessionKey, t, t + config.sessionTtlSec],
  );
  audit(req, "admin_login", { ok: true });
  res.json({ ok: true, session_key: sessionKey, expires_in: config.sessionTtlSec });
});

// Guard everything below EXCEPT login above. Path-scoped on purpose: this
// router is mounted without a prefix, so a bare router.use(adminAuth) would
// intercept unrelated paths (e.g. /api/nope would 401 instead of 404).
router.use("/admin", adminAuth);

// ---- GET /admin/stats --------------------------------------------------------
router.get("/admin/stats", async (_req, res) => {
  const t = now();
  const q = async (sql, params = []) => (await pool.query(sql, params)).rows[0].cnt;
  const [total, active5, alerts, banned, pro, founding] = await Promise.all([
    q("SELECT COUNT(*)::int AS cnt FROM users"),
    q("SELECT COUNT(*)::int AS cnt FROM users WHERE last_seen > $1", [t - 300]),
    q("SELECT COUNT(*)::int AS cnt FROM users WHERE alert_active = 1"),
    q("SELECT COUNT(*)::int AS cnt FROM users WHERE is_banned = 1"),
    q("SELECT COUNT(*)::int AS cnt FROM users WHERE is_pro = 1"),
    q("SELECT COUNT(*)::int AS cnt FROM users WHERE is_founding = 1"),
  ]);
  const totalAlerts = await q(
    "SELECT COALESCE(SUM(total_alerts), 0)::int AS cnt FROM users",
  );
  const recent = await pool.query(
    `SELECT user_id, device_name, platform, last_seen, is_banned, alert_active,
            alert_type, alert_ts, battery_pct, is_charging, total_alerts,
            is_pro, is_founding
     FROM users ORDER BY last_seen DESC LIMIT 50`,
  );

  res.json({
    ok: true,
    stats: {
      total_users: total,
      active_5min: active5,
      active_alerts: alerts,
      banned,
      pro,
      founding,
      total_alerts_sent: totalAlerts || 0,
    },
    recent_users: recent.rows,
  });
});

// ---- POST /admin/ban | /admin/unban -----------------------------------------
async function setBanned(req, res, value, word) {
  const userId = (req.body || {}).user_id;
  if (!userId) return res.status(400).json({ ok: false, error: "missing user_id" });
  await pool.query("UPDATE users SET is_banned = $1 WHERE user_id = $2", [value, userId]);
  audit(req, word, { user_id: userId });
  const payload = { ok: true };
  payload[word] = userId;
  res.json(payload);
}

router.post("/admin/ban", (req, res) => setBanned(req, res, 1, "banned"));
router.post("/admin/unban", (req, res) => setBanned(req, res, 0, "unbanned"));

// ---- POST /admin/broadcast ----------------------------------------------------
router.post("/admin/broadcast", async (req, res) => {
  const alertType = String((req.body || {}).alert_type || "TEST").toUpperCase().slice(0, 20);
  await pool.query(
    "UPDATE users SET alert_active = 1, alert_type = $1, alert_ts = $2 WHERE is_banned = 0",
    [alertType, now()],
  );
  audit(req, "broadcast", { alert_type: alertType });
  res.json({ ok: true, broadcast: alertType });
});

// ---- POST /admin/clear-all -----------------------------------------------------
router.post("/admin/clear-all", async (req, res) => {
  await pool.query("UPDATE users SET alert_active = 0, alert_type = ''");
  audit(req, "clear_all");
  res.json({ ok: true, cleared: true });
});

module.exports = router;
