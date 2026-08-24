// 6-digit device pairing. Codes carry a user_id (never a token); linking
// mints a fresh hashed linked_token and rotates it on re-link.
const express = require("express");
const pool = require("../db");
const config = require("../config");
const { sha256, randomToken, now } = require("../util");
const { authUser, purgeExpired } = require("../auth");

const router = express.Router();

// ---- POST /api/pair/generate ----------------------------------------------
router.post("/api/pair/generate", authUser, async (req, res) => {
  await purgeExpired(pool);
  const code = Math.floor(100000 + Math.random() * 900000).toString();
  await pool.query(
    "INSERT INTO pairing_codes (code, user_id, expires_at) VALUES ($1, $2, $3)",
    [code, req.user.user_id, now() + config.pairTtlSec],
  );
  res.json({ ok: true, code, expires_in: config.pairTtlSec });
});

// ---- POST /api/pair/link ---------------------------------------------------
router.post("/api/pair/link", async (req, res) => {
  const body = req.body || {};
  const code = String(body.code || "");
  if (!/^\d{6}$/.test(code)) {
    return res.status(400).json({ ok: false, error: "invalid_code" });
  }
  await purgeExpired(pool);

  const { rows } = await pool.query(
    "SELECT * FROM pairing_codes WHERE code = $1 AND expires_at > $2",
    [code, now()],
  );
  if (rows.length === 0) {
    return res.status(404).json({ ok: false, error: "invalid_or_expired" });
  }
  const record = rows[0];

  // Single-use: burn the code immediately so it can't be replayed.
  await pool.query("DELETE FROM pairing_codes WHERE code = $1", [code]);

  // Fresh linked token for the joining device; hash stored, plaintext
  // returned exactly once. Re-linking de-authorizes the previous phone.
  const linkedToken = randomToken();
  await pool.query(
    "UPDATE users SET linked_token = $1, last_seen = $2 WHERE user_id = $3",
    [sha256(linkedToken), now(), record.user_id],
  );

  res.json({ ok: true, token: linkedToken });
});

module.exports = router;
