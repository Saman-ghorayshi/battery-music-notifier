// Bearer-token auth middleware -- parity with worker.js authUser/adminAuth.
const pool = require("./db");
const config = require("./config");
const { sha256 } = require("./util");

function bearer(req) {
  const h = req.headers.authorization || "";
  return h.startsWith("Bearer ") ? h.slice(7).trim() : "";
}

async function purgeExpired(client) {
  const t = Math.floor(Date.now() / 1000);
  try {
    await client.query("DELETE FROM pairing_codes WHERE expires_at < $1", [t]);
    await client.query("DELETE FROM admin_sessions WHERE expires_at < $1", [t]);
  } catch (_) { /* opportunistic cleanup, never fatal */ }
}

// Resolves to the user row (or null). Banned users resolve to "banned" so
// routes can answer 403 with a clear error instead of a generic 401.
async function authUser(req, res, next) {
  const raw = bearer(req);
  if (!raw || raw.length < 16) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  const tokenHash = sha256(raw);
  const { rows } = await pool.query(
    "SELECT * FROM users WHERE token = $1 OR linked_token = $2 LIMIT 1",
    [tokenHash, tokenHash],
  );
  if (rows.length === 0) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  if (rows[0].is_banned) {
    return res.status(403).json({ ok: false, error: "banned" });
  }
  req.user = rows[0];
  next();
}

async function adminAuth(req, res, next) {
  const key = bearer(req);
  if (!key) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  await purgeExpired(pool);
  const { rows } = await pool.query(
    "SELECT 1 FROM admin_sessions WHERE session_key = $1 AND expires_at > $2",
    [key, Math.floor(Date.now() / 1000)],
  );
  if (rows.length === 0) {
    return res.status(401).json({ ok: false, error: "unauthorized" });
  }
  next();
}

module.exports = { authUser, adminAuth, purgeExpired, config };
