// Shared helpers -- crypto/time/ip. Rate limiting lives in rateLimit.js.

const crypto = require("crypto");

function sha256(text) {
  return crypto.createHash("sha256").update(text, "utf8").digest("hex");
}

function randomToken() {
  return crypto.randomBytes(24).toString("hex"); // 48 hex chars, same as worker.js
}

function now() {
  return Math.floor(Date.now() / 1000);
}

function clientIp(req) {
  return req.headers["cf-connecting-ip"] || req.ip || "unknown";
}

module.exports = { sha256, randomToken, now, clientIp };
