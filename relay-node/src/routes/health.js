// Health + landing. Looks like a boring generic page to obscure the API
// (same policy as the CF Worker).
const express = require("express");

const router = express.Router();

const okPage = "<html><body><h1>OK</h1></body></html>";

router.get(["/", "/health"], (_req, res) => {
  res.type("html").send(okPage);
});

module.exports = router;
