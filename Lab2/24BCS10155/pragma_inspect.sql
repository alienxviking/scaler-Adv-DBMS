-- Lab Session 2: SQLite3 storage-internals introspection
-- Run with:  sqlite3 students.db < pragma_inspect.sql

-- Create a small table so the file has pages to inspect.
CREATE TABLE IF NOT EXISTS students (
    id    INTEGER PRIMARY KEY,
    name  TEXT NOT NULL,
    gpa   REAL
);
INSERT INTO students (name, gpa) VALUES
    ('Alice', 3.8), ('Bob', 2.9), ('Carol', 3.5), ('Dave', 3.1);

-- ── Storage internals ──────────────────────────────────────────
PRAGMA page_size;        -- default 4096 bytes (matches OS page size)
PRAGMA page_count;        -- pages allocated; file size = page_size * page_count
PRAGMA freelist_count;    -- unused pages available for reuse

-- Memory-mapped I/O: 0 disables mmap, >0 enables it.
PRAGMA mmap_size;         -- current value (0 by default)
PRAGMA mmap_size = 268435456;  -- enable 256 MB mmap window
PRAGMA mmap_size;         -- confirm

-- ── Other useful PRAGMAs ───────────────────────────────────────
PRAGMA journal_mode;      -- WAL, DELETE, MEMORY, ...
PRAGMA cache_size;        -- number of pages held in memory
PRAGMA database_list;     -- attached databases
PRAGMA integrity_check;   -- validate all pages

SELECT count(*) AS student_count FROM students;
