# Lab Tasks Comparison Report: SQLite3 vs PostgreSQL

## Student Information
- **Name:** Snehangshu Roy
- **Role Number:** 24BCS10155

## 1. SQLite3 Exploration

### Commands Used
- To view file sizes: 
  ```bash
  ls -lh
  ```
- To find page size: 
  ```sql
  PRAGMA page_size;
  ```
- To find page count: 
  ```sql
  PRAGMA page_count;
  ```
- To check and change mmap size: 
  ```sql
  PRAGMA mmap_size;
  PRAGMA mmap_size=268435456; -- Example: changing to 256MB
  ```
- To time queries:
  ```bash
  time sqlite3 sample.db "SELECT * FROM users;"
  ```
- To observe the process: 
  ```bash
  ps aux | grep sqlite
  ```

### Observations
- **File Size:** The database file size (observed via `ls -lh`) grows proportionally as data is inserted into the tables.
- **Page Size:** The default page size in SQLite is 4096 bytes (4KB).
- **Page Count:** The page count command accurately reflects the total number of pages used by the SQLite database file to store data.
- **mmap_size Impact:** 
  - Memory-mapped I/O (mmap) allows SQLite to access the database file directly from memory instead of reading it into a separate buffer using standard I/O.
  - Increasing `mmap_size` reduces I/O latency and CPU overhead.
  - When comparing the execution time of `time SELECT * FROM users;`, enabling and increasing the `mmap_size` resulted in noticeably faster read query performance compared to standard I/O.

---

## 2. PostgreSQL (PSQL) Setup

### Commands Used
- To find page size (block size): 
  ```sql
  SHOW block_size;
  ```
- To find page count (number of blocks for a relation/table):
  ```sql
  SELECT relpages FROM pg_class WHERE relname = 'users';
  ```
- To time query execution within the PSQL console:
  ```sql
  \timing on
  SELECT * FROM users;
  ```

### Observations
- **Page Size:** PostgreSQL uses a larger default block size (page size) of 8192 bytes (8KB).
- **Page Count:** Unlike SQLite's global page count, PostgreSQL tracks pages per relation (table/index), which gives more granular insight into how space is allocated.
- **Query Performance:** Execution times are fast, but memory management is handled differently. PostgreSQL relies on its internal `shared_buffers` cache and the OS page cache rather than an explicit `mmap_size` parameter for basic query operations.

---

## 3. Comparison Analysis

| Feature | SQLite3 | PostgreSQL |
| :--- | :--- | :--- |
| **Default Page Size** | 4096 bytes (4KB) | 8192 bytes (8KB) |
| **Page Count Tracking** | Database-level (`PRAGMA page_count`) | Table-level (`pg_class.relpages`) |
| **Query Performance** | Exceptionally fast for local, read-heavy workloads. | Highly optimized for complex queries and concurrent read/write workloads. |
| **Memory/mmap Impact** | Explicitly configurable via `PRAGMA mmap_size`. Memory mapping significantly speeds up local read operations by avoiding data copying. | Relies on robust internal memory structures (`shared_buffers`) and OS caching. It is designed to handle memory for high concurrency rather than simple file mapping. |

### Conclusion
- **SQLite3** is lightweight and operates directly on a file. Tuning the `mmap_size` provides a significant performance boost for I/O operations by allowing direct memory access. It is best suited for scenarios where a simple, embedded database is required.
- **PostgreSQL** is a comprehensive, client-server RDBMS. Its larger default page size (8KB) and sophisticated memory management make it far more capable of handling large-scale, highly concurrent, and complex data workloads, though it requires more setup overhead than SQLite.
