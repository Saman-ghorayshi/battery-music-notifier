// Postgres connection pool.
const { Pool } = require("pg");
const config = require("./config");

// Bigint columns (epoch seconds) come back as strings by default -- parse them.
const types = require("pg").types;
types.setTypeParser(20, (v) => (v === null ? null : parseInt(v, 10)));

const pool = new Pool({
  connectionString: config.databaseUrl,
  max: 10,
  idleTimeoutMillis: 30_000,
});

pool.on("error", (err) => {
  console.error("[db] idle client error:", err.message);
});

module.exports = pool;
