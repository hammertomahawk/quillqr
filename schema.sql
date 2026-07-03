CREATE TABLE documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  read_slug TEXT NOT NULL UNIQUE,
  edit_token_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL,
  content_format TEXT NOT NULL CHECK (
    content_format IN ('text', 'markdown')
  ),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  edit_accessed_at TEXT,
  expires_at TEXT NOT NULL,
  deleted_at TEXT
);