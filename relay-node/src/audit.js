// JSONL audit trail for admin actions. One JSON object per line:
//   {"ts":"...","action":"ban","ip":"...","user_id":3}
// Human-grepable, append-only, cheap. AUDIT_FILE overrides the path.
const fs = require("fs");
const path = require("path");
const config = require("./config");
const { clientIp } = require("./util");

// 5 MB ceiling: JSONL lines are ~150 bytes, so this is years of admin events.
const AUDIT_MAX_BYTES = 5 * 1024 * 1024;

function rotateAuditIfNeeded(file) {
  try {
    if (!fs.existsSync(file)) return;
    if (fs.statSync(file).size < AUDIT_MAX_BYTES) return;
    fs.renameSync(file, file + ".old");
    console.log("[audit] rotated -> .old");
  } catch (e) {
    console.error("[audit] rotation failed:", e.message);
  }
}

function audit(req, action, detail = {}) {
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      action,
      ip: clientIp(req),
      ...detail,
    });
    fs.mkdirSync(path.dirname(config.auditFile), { recursive: true });
    rotateAuditIfNeeded(config.auditFile);
    fs.appendFileSync(config.auditFile, line + "\n");
  } catch (err) {
    // auditing must never break the request path
    console.error("[audit] write failed:", err.message);
  }
}

module.exports = audit;
