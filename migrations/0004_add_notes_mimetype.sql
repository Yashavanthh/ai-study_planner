-- Safe to re-run: ALTER TABLE ADD COLUMN is a no-op if column already exists in SQLite 3.37+
-- For older SQLite versions, we catch the error in Python.
ALTER TABLE notes ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'application/octet-stream';
