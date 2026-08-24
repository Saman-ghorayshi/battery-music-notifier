// JSONL audit trail for admin actions. One JSON object per line:
//   {"ts":"...","action":"ban","ip":"...","user_id":3}
// Human-grepable, append-only, cheap. AUDIT_FILE overrides the path.
const fs = require("fs");
const path = require("path");
const config = require("./config");
const { clientIp } = require("./util");

function audit(req, action, detail = {}) {
  try {
    const line = JSON.stringify({
      ts: new Date().toISOString(),
      action,
      ip: clientIp(req),
      ...detail,
    });
    fs.mkdirSync(path.dirname(config.auditFile), { recursive: true });
    fs.appendFileSync(config.auditFile, line + "\n");
  } catch (err) {
    // auditing must never break the request path
    console.error("[audit] write failed:", err.message);
  }
}

module.exports = audit;
