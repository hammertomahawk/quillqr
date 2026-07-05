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

CREATE TABLE IF NOT EXISTS pdf_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  read_slug TEXT NOT NULL UNIQUE,
  edit_token_hash TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL DEFAULT '',
  stored_filename TEXT NOT NULL,
  original_filename TEXT NOT NULL,
  file_size_bytes INTEGER NOT NULL,
  sanitized_at TEXT,
  pdf_sha256 TEXT,
  page_count INTEGER NOT NULL DEFAULT 0,
  text_char_count INTEGER NOT NULL DEFAULT 0,
  text_page_count INTEGER NOT NULL DEFAULT 0,
  text_page_percent REAL NOT NULL DEFAULT 0,
  safety_status TEXT NOT NULL DEFAULT 'unverified',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  edit_accessed_at TEXT,
  expires_at TEXT NOT NULL,
  deleted_at TEXT
);
