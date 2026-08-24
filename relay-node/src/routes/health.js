// Health + landing. Looks like a boring generic page to obscure the API
// (same policy as the CF Worker).
const express = require("express");

const router = express.Router();

const okPage = "<html><body><h1>OK</h1></body></html>";

// Plain-language privacy page (see SECURITY.md in the repo for the full model)
const privacyPage = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>Battery Relay Privacy</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:40px auto;line-height:1.5">
<h1>What this relay stores</h1>
<p>Per device: a <b>hashed</b> auth token, a device name you chose, your platform,
battery percentage, charging state, alert timestamps, and the last 200 alert events.</p>
<p>No accounts, no emails, no phone numbers, no location, no analytics.
Tokens are stored only as SHA-256 hashes. Pairing codes expire after 5 minutes.</p>
<p>This server never sends notifications on its own -- your devices deliver their own alerts.</p>
<p><a href="https://github.com/Saman-ghorayshi/battery-music-notifier/blob/main/SECURITY.md">Full security model</a></p>
</body></html>`;

router.get(["/", "/health"], (_req, res) => {
  res.type("html").send(okPage);
});

router.get("/privacy", (_req, res) => {
  res.type("html").send(privacyPage);
});

module.exports = router;
