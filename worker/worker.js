// Battery Notifier Cloud Relay - Cloudflare Worker
// D1-backed relay for 10k-50k users with token auth, rate limiting, admin dashboard
// Deploy on a throwaway domain for security-through-obscurity

const AUTH_PREFIX = "Bearer ";
const RATE_LIMIT_WINDOW = 60; // seconds
const RATE_LIMIT_MAX = 30; // requests per minute per user
const ADMIN_SESSION_TTL = 3600; // 1 hour
const MAX_EVENTS_PER_USER = 200; // keep event log bounded

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

function now() { return Math.floor(Date.now() / 1000); }

// ---- Rate limiting (in-memory, per-worker-instance) ----

const rateBuckets = new Map();

function checkRateLimit(userId) {
  const key = userId;
  const t = now();
  const bucket = rateBuckets.get(key);
  if (!bucket || t - bucket.window_start > RATE_LIMIT_WINDOW) {
    rateBuckets.set(key, { window_start: t, count: 1 });
    return true;
  }
  bucket.count++;
  return bucket.count <= RATE_LIMIT_MAX;
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
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
      "Cache-Control": "no-store",
    },
  });
}

function html(content, status = 200) {
  return new Response(content, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" },
  });
}

// ---- Auth: extract token from Authorization header ----

async function authUser(request, db) {
  const authHeader = request.headers.get("Authorization") || "";
  if (!authHeader.startsWith(AUTH_PREFIX)) return null;
  const token = authHeader.slice(AUTH_PREFIX.length).trim();
  if (!token || token.length < 16) return null;
  // Don't filter is_banned in SQL — return "banned" so the client gets a clear error
  const user = await db.prepare("SELECT * FROM users WHERE token = ?").bind(token).first();
  if (!user) return null;
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

async function handleRegister(request, db) {
  const body = await request.json().catch(() => ({}));
  const deviceName = (body.device_name || "").slice(0, 100);
  const platform = (body.platform || "").slice(0, 50);
  const token = randomToken();
  const t = now();

  const result = await db.prepare(
    "INSERT INTO users (token, device_name, platform, created_at, last_seen) VALUES (?, ?, ?, ?, ?)"
  ).bind(token, deviceName, platform, t, t).run();

  return json({ ok: true, token, user_id: result.meta.last_row_id });
}

async function handlePing(request, db, user) {
  const t = now();
  await db.prepare("UPDATE users SET last_seen = ? WHERE user_id = ?").bind(t, user.user_id).run();
  return json({ ok: true, server_time: t });
}

async function handleSendAlert(request, db, user, env) {
  const body = await request.json().catch(() => ({}));
  const alertType = (body.alert_type || "BATTERY").toUpperCase().slice(0, 20);

  // CRITICAL: Never rate-limit THIEF_ALERT. A thief unplugging the phone
  // must get through immediately, even if the user has been polling heavily.
  // Rate limiting is for registration/polling abuse, not safety alerts.
  const isCriticalAlert = alertType === "THIEF_ALERT";
  if (!isCriticalAlert && isRateLimitEnabled(env) && !checkRateLimit(user.user_id)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }
  cleanRateBuckets();
  await cleanExpiredSessions(db);
  const batteryPct = typeof body.battery_pct === "number" ? body.battery_pct : -1;
  const isCharging = body.is_charging ? 1 : 0;
  const t = now();

  await db.prepare(
    "UPDATE users SET alert_active = 1, alert_type = ?, alert_ts = ?, battery_pct = ?, is_charging = ?, total_alerts = total_alerts + 1, last_seen = ? WHERE user_id = ?"
  ).bind(alertType, t, batteryPct, isCharging, t, user.user_id).run();

  // Log event (bounded)
  await db.prepare(
    "INSERT INTO events (user_id, event_type, payload, ts) VALUES (?, ?, ?, ?)"
  ).bind(user.user_id, alertType, JSON.stringify({ battery_pct: batteryPct, charging: isCharging }), t).run();

  // Trim old events (only if count exceeds limit — avoids heavy subquery on every alert)
  const eventCount = await db.prepare("SELECT COUNT(*) as cnt FROM events WHERE user_id = ?").bind(user.user_id).first();
  if (eventCount.cnt > MAX_EVENTS_PER_USER) {
    const excess = eventCount.cnt - MAX_EVENTS_PER_USER;
    await db.prepare(
      "DELETE FROM events WHERE event_id IN (SELECT event_id FROM events WHERE user_id = ? ORDER BY event_id ASC LIMIT ?)"
    ).bind(user.user_id, excess).run();
  }

  return json({ ok: true, alert_active: 1, alert_type: alertType });
}

async function handleClearAlert(request, db, user) {
  await db.prepare(
    "UPDATE users SET alert_active = 0, alert_type = '', last_seen = ? WHERE user_id = ?"
  ).bind(now(), user.user_id).run();
  return json({ ok: true, alert_active: 0 });
}

async function handlePoll(request, db, user) {
  // User polls their own state (laptop checks if phone sent alert)
  return json({
    ok: true,
    alert_active: user.alert_active,
    alert_type: user.alert_type || "",
    alert_ts: user.alert_ts,
    battery_pct: user.battery_pct,
    is_charging: user.is_charging,
  });
}

// ---- Admin endpoints ----

async function handleAdminLogin(request, db, env) {
  // Guard: if ADMIN_KEY secret is not configured, don't allow login
  if (!env.ADMIN_KEY || env.ADMIN_KEY.length < 10) {
    return json({ ok: false, error: "admin_key_not_configured" }, 500);
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
  const sessionKey = await sha256(randomToken() + adminKey);
  const t = now();
  await db.prepare(
    "INSERT OR REPLACE INTO admin_sessions (session_key, created_at, expires_at) VALUES (?, ?, ?)"
  ).bind(sessionKey, t, t + ADMIN_SESSION_TTL).run();
  return json({ ok: true, session_key: sessionKey, expires_in: ADMIN_SESSION_TTL });
}

async function handleAdminStats(db) {
  const total = await db.prepare("SELECT COUNT(*) as cnt FROM users").first();
  const active = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE last_seen > ?").bind(now() - 300).first();
  const alerts = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE alert_active = 1").first();
  const banned = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_banned = 1").first();
  const pro = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_pro = 1").first();
  const founding = await db.prepare("SELECT COUNT(*) as cnt FROM users WHERE is_founding = 1").first();
  const totalAlerts = await db.prepare("SELECT SUM(total_alerts) as cnt FROM users").first();
  const recentUsers = await db.prepare("SELECT user_id, device_name, platform, last_seen, is_banned, alert_active, alert_type, alert_ts, battery_pct, is_charging, total_alerts, is_pro, is_founding FROM users ORDER BY last_seen DESC LIMIT 50").all();
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

function dashboardHTML(data) {
  const s = data.stats;
  const rows = (data.recent_users || []).map(u => `
    <tr>
      <td>${u.user_id}</td>
      <td>${u.device_name || '-'}</td>
      <td>${u.platform || '-'}</td>
      <td>${u.alert_active ? '<span class="alert">ACTIVE</span>' : 'idle'}</td>
      <td>${u.alert_type || '-'}</td>
      <td>${u.battery_pct >= 0 ? u.battery_pct + '%' : '-'}</td>
      <td>${u.is_charging ? 'charging' : '-'}</td>
      <td>${u.total_alerts}</td>
      <td>${u.is_banned ? 'BANNED' : (u.is_pro ? 'PRO' : (u.is_founding ? 'FOUNDING' : 'free'))}</td>
      <td><button class="ban-btn" data-uid="${u.user_id}">ban</button></td>
    </tr>`).join("");

  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Battery Relay Admin</title>
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
  // Generate a random 6-digit string
  const code = Math.floor(100000 + Math.random() * 900000).toString();
  const expiresAt = now() + 300; // 5 minutes from now
  
  await db.prepare("INSERT INTO pairing_codes (code, token, expires_at) VALUES (?, ?, ?)")
    .bind(code, user.token, expiresAt).run();
    
  return json({ ok: true, code: code, expires_in: 300 });
}

async function handlePairLink(request, db) {
  const body = await request.json().catch(() => ({}));
  const code = body.code;
  if (!code || code.length !== 6) return json({ ok: false, error: "invalid_code" }, 400);

  const record = await db.prepare("SELECT * FROM pairing_codes WHERE code = ? AND expires_at > ?")
    .bind(code, now()).first();
    
  if (!record) return json({ ok: false, error: "invalid_or_expired" }, 404);

  // Single-use: Delete the code immediately so it can't be reused
  await db.prepare("DELETE FROM pairing_codes WHERE code = ?").bind(code).run();

  return json({ ok: true, token: record.token });
}
// ---- Main router ----

export default {
  async fetch(request, env, ctx) {
    const db = env.DB;
    const url = new URL(request.url);
    const path = url.pathname;

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, { headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS", "Access-Control-Allow-Headers": "Content-Type, Authorization" } });
    }

    // ---- Public API ----
        // ---- Public API ----
    if (path === "/api/register" && request.method === "POST") return handleRegister(request, db);
    
    // 6-Digit Pairing System
    if (path === "/api/pair/generate" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      return u ? handlePairGenerate(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/pair/link" && request.method === "POST") {
      return handlePairLink(request, db);
    }

    if (path === "/api/ping" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      return u ? handlePing(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/alert" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      return u ? handleSendAlert(request, db, u, env) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/clear" && request.method === "POST") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      return u ? handleClearAlert(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
    }
    if (path === "/api/poll" && request.method === "GET") {
      const u = await authUser(request, db);
      if (u === "banned") return json({ ok: false, error: "banned" }, 403);
      return u ? handlePoll(request, db, u) : json({ ok: false, error: "unauthorized" }, 401);
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

    return json({ ok: false, error: "not_found" }, 404);
  },
};
