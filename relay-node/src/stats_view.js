// Shared stats collection for both the JSON API (/admin/stats) and the HTML
// dashboard. One source of truth for numbers.
const pool = require("./db");

async function collectStats() {
  const t = Math.floor(Date.now() / 1000);
  const q = async (sql, params = []) =>
    (await pool.query(sql, params)).rows[0].cnt;

  const [total, active5, alerts, bannedCount, pro, founding] = await Promise.all([
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
  const daily = await pool.query(
    "SELECT * FROM daily_stats ORDER BY day DESC LIMIT 30",
  );

  return {
    ok: true,
    stats: {
      total_users: total,
      active_5min: active5,
      active_alerts: alerts,
      banned: bannedCount,
      pro,
      founding,
      total_alerts_sent: totalAlerts || 0,
    },
    recent_users: recent.rows,
    daily: daily.rows,
  };
}

module.exports = { collectStats };
