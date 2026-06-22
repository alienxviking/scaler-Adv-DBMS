# Lab Session 2: SQLite3 Internals — mmap, Page Size, PRAGMA & Library Architecture

**Name:** Snehangshu Roy
**Roll No:** 24BCS10155

## Objective
Install SQLite3, inspect its storage internals via PRAGMA commands, understand
why SQLite is an in-process library (not a server), and document findings as
part of System Design Assignment 1 (PostgreSQL vs SQLite3).

## Files
- `pragma_inspect.sql` — storage-internals introspection script.
- `sqlite_demo.cpp` — C++ program linking `libsqlite3` directly (in-process).

## Part 1: Installation & Verification
```bash
sudo apt install sqlite3 libsqlite3-dev      # Ubuntu/Debian
sqlite3 --version
```

## Part 2: Storage Internals via PRAGMA
```bash
sqlite3 students.db < pragma_inspect.sql
```

- **`PRAGMA page_size;`** — default `4096` bytes (matches OS page size). The whole
  DB is one file divided into fixed-size pages; the page size is fixed at
  creation (changeable only via `VACUUM INTO`).
- **`PRAGMA page_count;`** — pages allocated. `file size = page_size * page_count`.
- **`PRAGMA mmap_size;`** — `0` disables mmap. Setting it (e.g. `268435456` = 256 MB)
  makes SQLite `mmap()` the DB file so reads become memory accesses instead of
  `read()` syscalls.

Verify the mmap effect via strace:
```bash
strace -e trace=mmap,openat,read sqlite3 students.db "SELECT count(*) FROM students;"
# mmap_size=0  -> many read() calls
# mmap_size>0  -> an mmap() call, then direct memory access (fewer/no read()s)
```

## Part 3: SQLite3 is a Library, Not a Process
```
Your application binary
  -> links libsqlite3.so (or statically embeds it)
       -> reads/writes the .db file directly via OS syscalls
```
- No server process, no TCP socket, no auth handshake — runs in the same
  process/address space as your app.
- Concurrency is via file-level locks (WAL mode improves this).

```bash
ps aux | grep sqlite        # nothing — only your own process
ldd $(which sqlite3)        # libsqlite3.so.0 => /lib/.../libsqlite3.so.0
```

Build and run the in-process demo:
```bash
g++ -std=c++17 -o sqlite_demo sqlite_demo.cpp -lsqlite3
./sqlite_demo students.db
```

## System Design Assignment 1: PostgreSQL vs SQLite3

| Dimension       | SQLite3                                    | PostgreSQL                                  |
|-----------------|--------------------------------------------|---------------------------------------------|
| Process model   | Library — runs inside your process         | Client-server — separate `postgres` daemon  |
| Communication   | Direct function calls / file I/O           | TCP (5432) or Unix socket                   |
| Concurrency     | File locks; one writer at a time (WAL helps)| MVCC — many readers + writers concurrently  |
| Authentication  | None (filesystem permissions)              | Users/roles/passwords/SSL                   |
| Storage         | Single `.db` file                          | Data directory with many files + WAL        |
| Transactions    | ACID (serialized writes)                   | Full ACID with MVCC isolation levels        |

**When to use SQLite3:** embedded apps (mobile/desktop/CLI), test/local DBs,
single-user or low-concurrency, zero-infrastructure, read-heavy workloads.

**When to use PostgreSQL:** multi-user concurrent writes, web backends/APIs,
row-level locking and advanced isolation, complex queries / extensions
(PostGIS, JSON, FTS), production auth/roles/SSL/auditing.

**How mmap fits in:** SQLite can `mmap()` the `.db` file so the OS page cache and
the process share the same physical pages — faster sequential reads. PostgreSQL
manages its own `shared_buffers` pool in the server process and does not rely on
mmap for its primary I/O path.

**Key insight:** SQLite's single-file, in-process design wins on portability and
simplicity; PostgreSQL's client-server MVCC design wins on concurrent multi-user
workloads. The right choice depends on who writes to the database and how many
do so at once.
