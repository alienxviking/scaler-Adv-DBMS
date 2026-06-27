# Work Distribution — Team QuorumDB

This document records how the MiniDB capstone was divided across the three team
members. The split follows the actual git commit history (each member authored
the commits for their area), so every member can demonstrate and defend their
own subsystems in the viva.

| Member | Roll Number | GitHub | Primary area |
|---|---|---|---|
| Rohan Ranjan | 24BCS10428 | `RohanRanjan250` | Storage engine, WAL infrastructure, query execution & optimizer, CLI |
| Rudhar Bajaj | 24BCS10143 | `rudhar07` | B+Tree indexing, transactions & concurrency, recovery, replication (Track D), benchmarks |
| Snehangshu Roy | 24BCS10155 | `alienxviking` | Catalog & type system, SQL parser/AST, engine integration, demos, documentation |

The work was deliberately partitioned so that the three required "pillars" of a
database — **storage/execution**, **transactions/recovery/replication**, and
**catalog/SQL-frontend/integration** — each have a clear owner, while the
interfaces between them were designed jointly.

---

## Rohan Ranjan (`RohanRanjan250`) — Storage, WAL, Execution, CLI

**Commits:** storage engine · WAL records+manager+page-ops · SQL operators +
optimizer + executor · CLI.

### 1. Storage engine — `src/minidb/storage/`
- **Slotted page format** (`page.py`): 4 KiB page layout with a header
  (page-LSN, slot count, free-space pointer), a slot directory growing forward,
  and records growing backward. Stable **RID = (page_id, slot_no)**, tombstone
  deletes, slot reuse, and the deterministic `apply_insert/delete/update` replay
  hooks used by recovery and replication.
- **Disk manager** (`disk_manager.py`): single-file paged store; page
  allocate/read/write and `fsync`; allocates *initialised* empty pages so an
  unflushed page is still well-formed for redo.
- **Buffer pool** (`buffer_pool.py`): fixed frames, pin/unpin, dirty tracking,
  **CLOCK** replacement, hit/miss stats, and enforcement of the **write-ahead
  rule** (flush the log up to a page's LSN before writing that dirty page).
- **Heap file** (`heapfile.py`): per-table page set, free-space-tracked inserts,
  tombstone deletes, sequential scan, and per-mutation WAL logging hooks.

### 2. Write-ahead log infrastructure — `src/minidb/wal/log_record.py`, `log_manager.py`, `page_ops.py`
- **Physiological log records**: before/after images, per-transaction prev-LSN
  chain, binary + length-framed encodings (reused by recovery *and* replication).
- **Log manager**: monotonic LSN assignment, append + `fsync`-backed
  `flush(lsn)`, in-memory mirror, torn-tail tolerance on load.
- **page_ops**: the single redo/undo→page mapping shared by recovery, abort, and
  the replica.

### 3. Query execution & optimizer — `src/minidb/sql/plan.py`, `optimizer.py`, `executor.py`
- **Volcano iterator operators**: `SeqScan`, `IndexScan`, `Filter`,
  `NestedLoopJoin`, `Projection`, each rendering an EXPLAIN line.
- **Cost-based optimizer**: selectivity estimation (1/ndv for key equality,
  range/neq heuristics), SeqScan-vs-IndexScan cost comparison, and greedy
  size-based join ordering over the ON-predicate graph.
- **Executor**: DDL, INSERT (pre-checked uniqueness + index maintenance),
  index-or-scan DELETE, SELECT via the optimized plan.

### 4. Command-line interface — `src/minidb/cli.py`
- Interactive REPL: multi-line `;`-terminated SQL, aligned result tables,
  `EXPLAIN`, and `.tables` / `.schema` / `.stats` introspection commands.

**Viva talking points:** slotted-page mechanics & why RIDs stay stable, CLOCK
eviction, the write-ahead rule, the iterator model, and how the optimizer
chooses an access path.

---

## Rudhar Bajaj (`rudhar07`) — Indexing, Transactions, Recovery, Replication, Benchmarks

**Commits:** B+Tree index · transactions + 2PL + recovery · replication
(Track D) · benchmark harness + report.

### 1. B+Tree indexing — `src/minidb/index/bplustree.py`
- Balanced B+Tree mapping ordered keys → RID lists: root-to-leaf search,
  **range scans** over linked leaves, **insert** with leaf/internal **splits**,
  **delete** with sibling **borrow/merge** rebalancing and root collapse.
- **Unique** (primary key) vs **non-unique** (secondary index) modes;
  `num_keys()`/`height()` diagnostics for the optimizer.
- Validated by a 2,000-operation randomized fuzz test vs a reference dict.

### 2. Transactions & concurrency — `src/minidb/txn/lock_manager.py`, `transaction.py`
- **Strict 2PL** lock manager: S/X locks on table resources, lock upgrade, and
  a **waits-for graph with cycle detection** that picks a deadlock victim.
- **Transactions**: per-txn logging + prev-LSN chain, **commit** (flush log =
  durable), **abort** (reverse undo writing CLRs).

### 3. Crash recovery — `src/minidb/wal/recovery.py`
- **ARIES** three-pass recovery: **analysis** (winners/losers + touched pages),
  **redo** ("repeat history", guarded by page LSN), **undo** (idempotent
  rollback of losers). Reconciles heap page lists discovered in the log.

### 4. Replication (Extension Track D) — `src/minidb/replication/`
- **Protocol** (`protocol.py`): length-framed CATALOG/RECORDS/ACK/HEARTBEAT
  messages reusing the WAL record encoding.
- **Primary** (`primary.py`): streams catalog snapshot + redo log to replicas,
  pushes new records live, tracks per-replica acked LSN (lag).
- **Replica** (`replica.py`): applies redo as "continuous recovery", rebuilds
  indexes for read consistency, and **promotes** on failover.

### 5. Benchmarks — `benchmarks/run_benchmarks.py`, `REPORT.md`
- Four experiments: index-vs-scan, autocommit-vs-batched-txn throughput,
  buffer-pool hit ratio vs pool size, replication apply throughput; with
  analysis and limitations.

**Viva talking points:** B+Tree split/merge, strict 2PL serializability,
deadlock detection, the ARIES redo/undo passes, and how replication reuses the
WAL redo path.

---

## Snehangshu Roy (`alienxviking`) — Catalog, SQL Front-end, Integration, Docs

**Commits:** project scaffold · catalog + type system · SQL AST + parser ·
engine facade + connections · demos · README + architecture docs.

### 1. Project scaffold & architecture — repository layout
- Package structure (`storage/index/sql/catalog/txn/wal/replication`),
  `pyproject.toml`, `.gitignore`, and the layered design the team built against.

### 2. Catalog & type system — `src/minidb/catalog/schema.py`, `catalog.py`
- **Type system**: INT/FLOAT/TEXT/BOOL, nullable columns, value coercion, and a
  compact **null-bitmap tuple serializer** (the on-disk record format).
- **System catalog**: per-table schema/PK/page-list/index metadata, atomic JSON
  persistence, index rebuild-from-heap, and `to_doc()/load_from_doc()` used by
  replicas.

### 3. SQL parser & AST — `src/minidb/sql/parser.py`, `ast.py`
- Hand-written **tokenizer** + **recursive-descent parser** producing the AST:
  CREATE TABLE/INDEX, DROP, INSERT (multi-row), DELETE, SELECT with projection,
  table aliases, INNER JOIN … ON, WHERE (AND of comparisons), BEGIN/COMMIT/
  ROLLBACK.

### 4. Engine integration — `src/minidb/engine.py`
- **`Database` facade** wiring every subsystem and running recovery on startup
  (replay → reconcile page lists → rebuild indexes); `checkpoint()/close()`.
- **`Connection`** sessions: autocommit + explicit transactions, EXPLAIN, and a
  shared lock manager across concurrent sessions.

### 5. Demos & documentation — `demos/`, `README.md`, `docs/ARCHITECTURE.md`
- Four runnable demos (SQL, concurrency/deadlock, recovery, replication).
- The 12-section README and architecture notes (dependency graph, invariants,
  operation lifecycles).

**Viva talking points:** the tuple/null-bitmap format, catalog persistence vs
WAL recovery, recursive-descent parsing, and how the engine wires recovery +
indexing on startup.

---

## Shared / jointly-owned work
- **Interfaces between layers** (RID, log-record schema, execution context) were
  designed together so subsystems compose cleanly.
- **Testing**: the 48-test suite (`tests/`) spans all areas; each member wrote
  the tests for their own modules, reviewed jointly.
- **Integration & end-to-end SQL tests** (`tests/test_sql_engine.py`) were a
  joint effort across the parser, executor, txn, and recovery owners.

## Module → owner quick reference
| Path | Owner |
|---|---|
| `storage/*`, `wal/log_record.py`, `wal/log_manager.py`, `wal/page_ops.py` | Rohan Ranjan |
| `sql/plan.py`, `sql/optimizer.py`, `sql/executor.py`, `cli.py` | Rohan Ranjan |
| `index/bplustree.py` | Rudhar Bajaj |
| `txn/*`, `wal/recovery.py` | Rudhar Bajaj |
| `replication/*`, `benchmarks/*` | Rudhar Bajaj |
| `catalog/*` | Snehangshu Roy |
| `sql/ast.py`, `sql/parser.py`, `sql/context.py` | Snehangshu Roy |
| `engine.py`, `demos/*`, `README.md`, `docs/*` | Snehangshu Roy |
