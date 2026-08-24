/* Battery Music Notifier GUI -- vanilla JS, no build step.
   Polls pywebview.api.get_state() on a timer; everything else is on-demand. */
"use strict";

const $ = (id) => document.getElementById(id);
const api = () => window.pywebview?.api;

let settingsCache = null;

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $("view-" + btn.dataset.view).classList.add("active");
  });
});

/* ---------------- dashboard ---------------- */
function renderState(s) {
  const pct = s.battery_pct ?? -1;
  const charging = !!s.charging;
  $("ring-pct").textContent = pct >= 0 ? pct + "%" : "--%";
  $("ring-state").textContent = charging ? "charging" : pct >= 0 ? "on battery" : "no battery";
  const C = 502;
  const frac = pct >= 0 ? Math.max(0, Math.min(100, pct)) / 100 : 0;
  $("ring").style.strokeDashoffset = String(C * (1 - frac));
  $("ring").style.stroke = charging ? "#00d478" : pct <= 20 ? "#ff4757" : "#00d4ff";

  const hb = s.heartbeat || {};
  const dot = $("hb-dot");
  dot.className = "dot" + (hb.ok === true ? " ok" : hb.ok === false ? " bad" : "");
  $("hb-text").textContent =
    hb.ok === true ? "online" : hb.ok === false ? "unreachable" : "checking...";

  setBadge($("relay-badge"), s.relay?.running, s.relay?.error, "relay", "stopped");
  setBadge($("serve-badge"), s.serve?.running, s.serve?.error, "listening", "stopped");

  $("last-alert").textContent = s.relay?.last_alert || "none";
  $("btn-relay").textContent = s.relay?.running ? "Stop Relay" : "Start Relay";
  $("btn-serve").textContent = s.serve?.running ? "Stop Socket Server" : "Start Socket Server";
}

function setBadge(el, on, err, onText, offText) {
  el.textContent = err && !on ? offText + ": " + err : on ? onText : offText;
  el.className = "badge" + (on ? " on" : err ? " err" : " off");
}

$("btn-relay").addEventListener("click", async () => {
  if (!api()) return;
  const running = $("btn-relay").textContent.startsWith("Stop");
  await api()[running ? "stop_relay" : "start_relay"]();
});
$("btn-serve").addEventListener("click", async () => {
  if (!api()) return;
  const running = $("btn-serve").textContent.startsWith("Stop");
  await api()[running ? "stop_serve" : "start_serve"]();
});

/* ---------------- thief catcher ---------------- */
let armTime = 0;
$("thief-toggle").addEventListener("click", async () => {
  if (!api()) return;
  const armed = $("thief-toggle").classList.contains("armed");
  if (armed) {
    await api().disarm_thief();
    armTime = 0;
  } else {
    const force = $("thief-force").checked;
    await api().arm_thief(force);
    armTime = Date.now();
  }
});

function renderThief(s) {
  const t = s.thief || {};
  const btn = $("thief-toggle");
  btn.classList.toggle("armed", !!t.armed);
  btn.textContent = t.armed ? "ARMED" : "DISARMED";
  // grace countdown ring: visible only during the 3s post-arm window
  const GRACE = 3000;
  const elapsed = Date.now() - armTime;
  const inGrace = t.armed && elapsed >= 0 && elapsed < GRACE && armTime > 0;
  const C = 314;
  const ring = $("grace-ring");
  ring.style.opacity = inGrace ? "1" : "0";
  ring.style.strokeDashoffset = String(inGrace ? C * (1 - elapsed / GRACE) : C);
  $("grace-label").textContent = t.armed
    ? inGrace ? "starting..." : t.alert_active ? "ALARM ACTIVE" : "watching the charger"
    : "";
}

/* ---------------- pair ---------------- */
$("btn-pair").addEventListener("click", async () => {
  if (!api()) return;
  $("pair-error").textContent = "";
  const r = await api().pair_generate();
  if (!r || !r.ok) {
    $("pair-result").classList.add("hidden");
    $("pair-error").textContent = (r && r.error) || "failed";
    return;
  }
  $("pair-code").textContent = r.code;
  const qr = $("pair-qr");
  if (r.qr) { qr.src = r.qr; qr.classList.remove("hidden"); }
  $("pair-result").classList.remove("hidden");
});

/* ---------------- file pickers ---------------- */
document.querySelectorAll("[data-pick]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!api()) return;
    const key = btn.dataset.pick;
    const r = await api().pick_files(key === "alarm_files" ? "alarm" : "music");
    if (r && r.ok && r.files.length) {
      settingsCache[key] = [...new Set([...(settingsCache[key] || []), ...r.files])];
      renderFileLists();
    }
  });
});

function renderFileLists() {
  for (const [key, listId] of [["music_files", "music-list"], ["alarm_files", "alarm-list"]]) {
    const wrap = $(listId);
    wrap.innerHTML = "";
    (settingsCache?.[key] || []).forEach((f, i) => {
      const row = document.createElement("div");
      row.className = "fileitem";
      const name = document.createElement("span");
      name.textContent = f.split(/[\\/]/).pop();
      name.title = f;
      const x = document.createElement("button");
      x.type = "button"; x.textContent = "x";
      x.addEventListener("click", () => {
        settingsCache[key].splice(i, 1);
        renderFileLists();
      });
      row.append(name, x);
      wrap.appendChild(row);
    });
  }
}

/* ---------------- settings form ---------------- */
function fillHourSelects() {
  for (const id of ["quiet-start", "quiet-end"]) {
    const sel = $(id);
    sel.innerHTML = "";
    for (let h = 0; h < 24; h++) {
      const o = document.createElement("option");
      o.value = h; o.textContent = String(h).padStart(2, "0") + ":00";
      sel.appendChild(o);
    }
  }
}
fillHourSelects();

async function loadSettings() {
  if (!api()) return;
  const r = await api().get_settings();
  if (!r || !r.ok) return;
  settingsCache = r.settings;
  const st = r.settings;
  $("min_percentage").value = st.min_percentage;
  $("max_percentage").value = st.max_percentage;
  $("volume").value = Math.round((st.volume ?? 0.8) * 100);
  $("poll_interval").value = st.poll_interval;
  $("annoying").checked = !!st.annoying;
  $("autostart").checked = !!st.autostart;
  $("worker_url").value = st.worker_url || "";
  $("telegram_token").value = st.telegram_token || "";
  $("telegram_chat_id").value = st.telegram_chat_id || "";
  $("email_smtp_server").value = st.email_smtp_server || "";
  $("email_smtp_port").value = st.email_smtp_port;
  $("email_sender").value = st.email_sender || "";
  $("email_password").value = st.email_password || "";
  $("email_receiver").value = st.email_receiver || "";
  $("admin_key").value = st.admin_key || "";
  $("socket_secret").value = st.socket_secret || "";
  const qh = Array.isArray(st.quiet_hours) ? st.quiet_hours : [22, 8];
  $("quiet-start").value = qh[0] ?? 22;
  $("quiet-end").value = qh[1] ?? 8;
  // proxy radio
  const p = st.proxy_url || "";
  const mode = p === "" ? "auto" : p.toLowerCase() === "direct" ? "direct" : "url";
  document.querySelector(`input[name=proxy][value=${mode}]`).checked = true;
  $("proxy_url_text").value = mode === "url" ? p : "";
  syncOutputs();
  renderFileLists();
}

function syncOutputs() {
  $("volume-out").textContent = $("volume").value;
  $("min-out").textContent = $("min_percentage").value;
  $("max-out").textContent = $("max_percentage").value;
}
["volume", "min_percentage", "max_percentage"].forEach((id) =>
  $(id).addEventListener("input", syncOutputs));

$("btn-save").addEventListener("click", async () => {
  if (!api()) return;
  // pywebview injects the bridge asynchronously: make sure settings are
  // loaded before saving, or the save would silently no-op.
  if (!settingsCache) await loadSettings();
  if (!settingsCache) return;
  const proxyMode = document.querySelector("input[name=proxy]:checked").value;
  const payload = {
    ...settingsCache,
    min_percentage: +$("min_percentage").value,
    max_percentage: +$("max_percentage").value,
    volume: +$("volume").value / 100,
    poll_interval: +$("poll_interval").value,
    annoying: $("annoying").checked,
    quiet_hours: [+$("quiet-start").value, +$("quiet-end").value],
    proxy_url: proxyMode === "auto" ? ""
             : proxyMode === "direct" ? "direct"
             : $("proxy_url_text").value.trim(),
    worker_url: $("worker_url").value.trim(),
    telegram_token: $("telegram_token").value,
    telegram_chat_id: $("telegram_chat_id").value.trim(),
    email_smtp_server: $("email_smtp_server").value.trim(),
    email_smtp_port: +$("email_smtp_port").value || 587,
    email_sender: $("email_sender").value.trim(),
    email_password: $("email_password").value,
    email_receiver: $("email_receiver").value.trim(),
    admin_key: $("admin_key").value,
    socket_secret: $("socket_secret").value,
  };
  const r = await api().save_settings(payload);
  $("save-status").textContent = r && r.ok ? "Saved." : "Save failed.";
  setTimeout(() => ($("save-status").textContent = ""), 2500);
  if (r && r.ok) loadSettings();
});

/* ---------------- diagnostics ---------------- */
$("btn-doc").addEventListener("click", async () => {
  if (!api()) return;
  $("doc-cards").innerHTML = "<p class='muted'>Running checks...</p>";
  const r = await api().run_diagnostics();
  const wrap = $("doc-cards");
  wrap.innerHTML = "";
  (r.sections || []).forEach((sec) => {
    const card = document.createElement("div");
    card.className = "card doc-card" + (sec.ok ? "" : " bad");
    const h = document.createElement("h2");
    h.innerHTML = `<span>${sec.title}</span><span>${sec.ok ? "OK" : "!"}</span>`;
    const pre = document.createElement("pre");
    pre.textContent = sec.body.trimEnd() || "(no details)";
    card.append(h, pre);
    wrap.appendChild(card);
  });
});

/* ---------------- logs ---------------- */
$("btn-log-refresh").addEventListener("click", refreshLogs);
async function refreshLogs() {
  if (!api()) return;
  const r = await api().get_logs(300);
  $("log-view").textContent = r?.text ?? "(log unavailable)";
}

/* ---------------- poll loop ---------------- */
// single combined poll to keep IPC cheap
setInterval(async () => {
  try {
    if (!api()) return;
    const s = await api().get_state();
    renderState(s);
    renderThief(s);
  } catch (e) { /* ignore until backend ready */ }
}, 1500);

/* pywebview injects window.pywebview AFTER page load, so anything that
   needs the bridge must wait for the `pywebviewready` event (with a poll
   fallback in case the event fired before we attached). */
function whenReady(cb) {
  if (api()) { cb(); return; }
  const t0 = Date.now();
  const iv = setInterval(() => {
    if (api() || Date.now() - t0 > 15000) {
      clearInterval(iv);
      cb();
    }
  }, 100);
  window.addEventListener("pywebviewready", () => {
    clearInterval(iv);
    cb();
  }, { once: true });
}

window.addEventListener("DOMContentLoaded", () => {
  whenReady(() => {
    loadSettings();
    refreshLogs();
  });
});
