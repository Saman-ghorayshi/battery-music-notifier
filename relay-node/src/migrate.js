#!/usr/bin/env node
// Tiny ordered-SQL migrator: applies migrations/*.sql in filename order,
// tracking applied files in schema_migrations. Idempotent.
const fs = require("fs");
const path = require("path");

const pool = require("./db");

async function migrate() {
  const client = await pool.connect();
  try {
    await client.query(`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        name TEXT PRIMARY KEY,
        applied_at BIGINT DEFAULT (EXTRACT(EPOCH FROM now()))::bigint
      )`);

    const dir = path.join(__dirname, "..", "migrations");
    const files = fs.readdirSync(dir).filter((f) => f.endsWith(".sql")).sort();

    for (const file of files) {
      const applied = await client.query("SELECT 1 FROM schema_migrations WHERE name = $1", [file]);
      if (applied.rowCount > 0) {
        console.log(`  = ${file} (already applied)`);
        continue;
      }
      const sql = fs.readFileSync(path.join(dir, file), "utf8");
      await client.query("BEGIN");
      try {
        await client.query(sql);
        await client.query("INSERT INTO schema_migrations (name) VALUES ($1)", [file]);
        await client.query("COMMIT");
        console.log(`  + ${file} applied`);
      } catch (err) {
        await client.query("ROLLBACK");
        throw new Error(`${file}: ${err.message}`);
      }
    }
    console.log("Migrations complete.");
  } finally {
    client.release();
    await pool.end();
  }
}

migrate().catch((err) => {
  console.error("Migration failed:", err.message);
  process.exit(1);
});
