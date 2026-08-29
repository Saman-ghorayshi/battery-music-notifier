-- v2.2 migration: opt-in per-account Telegram delivery.
-- Run once per environment:
--   npx wrangler d1 execute DB --file=migration_notify.sql --remote

CREATE TABLE IF NOT EXISTS user_notify (
  user_id INTEGER PRIMARY KEY,
  bot_token TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
