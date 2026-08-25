// HTML admin dashboard for relay-node (browser parity with the CF worker's).
// Server-rendered, zero external assets, everything escaped. The JSON admin
// API stays untouched so the Python CLI keeps working.
//
// Routes added here (mounted before routes/admin.js):
//   GET /admin            -> login page OR rendered dashboard
//   GET /admin/audit.json -> last N lines of the JSONL audit log (authed)
const fs = require("fs");
const path = require("path");
const express = require("express");
const pool = require("../db");
const config = require("../config");
const { adminAuth } = require("../auth");
const { ensureDailyStats } = require("../stats");

const router = express.Router();

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function bearer(req) {
  const h = req.headers.authorization || "";
  return h.startsWith("Bearer ") ? h.slice(7).trim() : "";
}

async function sessionValid(key) {
  if (!key) return false;
  const { rows } = await pool.query(
    "SELECT 1 FROM admin_sessions WHERE session_key = $1 AND expires_at > $2",
    [key, Math.floor(Date.now() / 1000)],
  );
  return rows.length > 0;
}

function readAuditTail(lines = 200) {
  try {
    if (!fs.existsSync(config.auditFile)) return [];
    const raw = fs.readFileSync(config.auditFile, "utf8").trim();
    if (!raw) return [];
    return raw.split("\n").slice(-lines)
      .map((l) => { try { return JSON.parse(l); } catch (_) { return null; } })
      .filter(Boolean)
      .reverse(); // newest first
  } catch (_) {
    return [];
  }
}

// ---- pages -----------------------------------------------------------------

const STYLE = `
body{font-family:monospace;background:#1a1a2e;color:#e0e0e0;margin:20px}
h1{color:#00d4ff}h2{color:#ff9f43;margin-top:26px}
.card{background:#16213e;padding:14px;border-radius:8px;border:1px solid #30475e;display:inline-block;margin:6px;min-width:150px}
.label{color:#888;font-size:11px;text-transform:uppercase}
.value{font-size:26px;font-weight:bold;color:#00d4ff}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:10px}
th,td{border:1px solid #30475e;padding:5px 9px;text-align:left}
th{background:#16213e;color:#00d4ff}
tr:nth-child(even){background:#16213e}
button{background:#30475e;color:#fff;border:none;padding:3px 9px;border-radius:4px;cursor:pointer;font-size:11px}
button:hover{background:#00d4ff;color:#1a1a2e}
.big{background:#30475e;color:#fff;border:none;padding:8px 16px;border-radius:4px;margin:8px 8px 0 0;cursor:pointer}
input{padding:12px;width:300px;font-size:15px;background:#16213e;color:#e0e0e0;border:1px solid #30475e;border-radius:4px}
svg{background:#12121f;border-radius:6px}
.audit td{font-size:11px;color:#aaa}
`;

function sparkline(daily) {
  const rows = (daily || []).slice().reverse(); // oldest -> newest
  if (!rows.length) return "<i>no daily data yet</i>";
  const max = Math.max(1, ...rows.map((r) => r.alerts || 0));
  const w = 520, h = 90;
  const pts = rows.map((r, i) => {
    const x = (i / Math.max(1, rows.length - 1)) * (w - 8) + 4;
    const y = h - 6 - ((r.alerts || 0) / max) * (h - 16);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const todayRow = rows[rows.length - 1];
  return `<svg width="${w}" height="${h}">` +
    `<polyline fill="none" stroke="#00d4ff" stroke-width="2" points="${pts}"/>` +
    `</svg><div class="label">${escapeHtml(todayRow.day)}: ` +
    `${todayRow.alerts ?? "-"} alerts · ${todayRow.registrations ?? "-"} new · ` +
    `${todayRow.active_devices ?? "-"} active · ${todayRow.pairings ?? 0} pairings</div>`;
}

function loginPage() {
  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Battery Relay Admin</title><style>${STYLE}</style></head><body>
<h2>Admin Login</h2>
<input id="key" type="password" placeholder="Admin key"><br>
<button onclick="login()">Login</button>
<p class="label">Session lasts 1 hour.</p>
<script>
async function login(){
  const r = await fetch('/admin/login',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({admin_key:document.getElementById('key').value})});
  const d = await r.json();
  if(d.ok){localStorage.setItem('sk',d.session_key);location.reload();}
  else alert('Invalid key');
}
</script></body></html>`;
}

function dashboardPage(data, audit) {
  const s = data.stats;
  const card = (label, val) =>
    `<div class="card"><div class="label">${label}</div><div class="value">${val}</div></div>`;

  const userRows = (data.recent_users || []).map((u) => {
    const uid = escapeHtml(u.user_id);
    return `<tr><td>${uid}</td>` +
      `<td>${escapeHtml(u.device_name || "-")}</td>` +
      `<td>${escapeHtml(u.platform || "-")}</td>` +
      `<td>${u.alert_active ? '<span style="color:#ff4757">ACTIVE</span>' : "idle"}</td>` +
      `<td>${escapeHtml(u.alert_type || "-")}</td>` +
      `<td>${u.battery_pct >= 0 ? u.battery_pct + "%" : "-"}</td>` +
      `<td>${u.is_charging ? "charging" : "-"}</td>` +
      `<td>${Number(u.total_alerts) || 0}</td>` +
      `<td>${u.is_banned ? "BANNED" : u.is_pro ? "PRO" : u.is_founding ? "FOUNDING" : "free"}</td>` +
      `<td><button data-act="ban" data-uid="${uid}">ban</button> ` +
      `<button data-act="unban" data-uid="${uid}">unban</button></td></tr>`;
  }).join("");

  const auditRows = (audit || []).map((e) =>
    `<tr class="audit"><td>${escapeHtml(e.ts)}</td><td>${escapeHtml(e.action)}</td>` +
    `<td>${escapeHtml(String(e.ip))}</td><td>${escapeHtml(JSON.stringify(e))}</td></tr>`
  ).join("");

  return `<!DOCTYPE html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:">
<title>Battery Relay Admin</title><style>${STYLE}</style></head><body>
<h1>Battery Relay Admin <span class="label">(node)</span></h1>
<div>
${card("Total Users", s.total_users)}
${card("Active (5min)", s.active_5min)}
${card("Active Alerts", s.active_alerts)}
${card("Total Alerts Sent", s.total_alerts_sent)}
${card("Banned", s.banned)}
${card("Pro", s.pro)}
${card("Founding", s.founding)}
</div>
<div class="card" style="display:block;max-width:560px">
<div class="label">Alerts per day (aggregate only)</div>
${sparkline(data.daily)}
</div>
<div class="actions" style="margin:16px 0">
<button class="big" onclick="doPost('/admin/broadcast','TEST')">Broadcast TEST</button>
<button class="big" onclick="doPost('/admin/clear-all')">Clear All Alerts</button>
<button class="big" onclick="location.reload()">Refresh</button>
</div>
<h2>Recent Users</h2>
<table><tr><th>ID</th><th>Device</th><th>Platform</th><th>Alert</th><th>Type</th>
<th>Batt</th><th>Chg</th><th>Total</th><th>Plan</th><th>Action</th></tr>
${userRows || '<tr><td colspan="10">none</td></tr>'}</table>
<h2>Audit Log (latest)</h2>
<table class="audit"><tr><th>ts</th><th>action</th><th>ip</th><th>raw</th></tr>
<tr><td colspan="4" id="audit-loading">loading…</td></tr></table>
<script>
const SK = localStorage.getItem('sk');
const AUTH = {'Authorization':'Bearer '+SK,'Content-Type':'application/json'};
async function doPost(url, alertType){
  const body = alertType ? JSON.stringify({alert_type:alertType}) : '{}';
  await fetch(url,{method:'POST',headers:AUTH,body});
  location.reload();
}
document.querySelectorAll('[data-act]').forEach(b=>{
  b.addEventListener('click',()=>doPost('/admin/'+b.dataset.act,b.dataset.uid));
});
fetch('/admin/audit.json?lines=100',{headers:AUTH})
  .then(r=>r.json())
  .then(d=>{
    const tb=document.querySelector('.audit');
    tb.innerHTML='<tr><th>ts</th><th>action</th><th>ip</th><th>raw</th></tr>'+
      (d.events||[]).map(e=>'<tr class="audit"><td>'+e.ts+'</td><td>'+e.action+
        '</td><td>'+e.ip+'</td><td>'+JSON.stringify(e)+'</td></tr>').join('');
  }).catch(()=>{});
</script>
</body></html>`;
}

// ---- routes ------------------------------------------------------------------

router.get("/admin/audit.json", adminAuth, (req, res) => {
  const lines = Math.min(parseInt(req.query.lines, 10) || 200, 1000);
  res.json({ ok: true, events: readAuditTail(lines) });
});

router.get("/admin", async (req, res) => {
  const authHeader = req.headers.authorization || "";
  if (!authHeader && req.query.session) {
    // convenience: /admin?session=<key> lets the login page redirect cleanly
    req.headers.authorization = `Bearer ${req.query.session}`;
  }
  const key = bearer(req);
  const ok = await sessionValid(key);
  if (!ok) {
    // A Bearer that failed means an expired session -> clear it client-side.
    const clearScript = authHeader
      ? "<script>localStorage.removeItem('sk');location.reload()</script>"
      : "";
    return res.status(401).type("html").send(loginPage() + clearScript);
  }

  await ensureDailyStats(true).catch(() => {});
  const { collectStats } = require("../stats_view");
  const data = await collectStats();
  res.type("html").send(dashboardPage(data, readAuditTail(200)));
});

module.exports = router;
