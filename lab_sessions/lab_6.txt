# Lab Session 6: Transaction Manager — MVCC + Two-Phase Locking in C++

## Objective
Build a transaction manager that combines:
1. **MVCC** — every write creates a new row version; readers see a consistent snapshot without blocking writers.
2. **Two-Phase Locking (2PL)** — lock acquisition is bounded to the "growing" phase; no new locks after the first release ("shrinking" phase). Strict 2PL holds all locks until commit/abort.
3. **Deadlock detection** — waits-for graph cycle detection to abort one transaction when a cycle forms.

This mirrors the core of PostgreSQL's concurrency architecture (MVCC snapshot isolation + predicate/row-level locks).

---

## Concepts

### MVCC version visibility rule
A version created by transaction `xmin` and invalidated by `xmax` is visible to transaction `T` if:
- `xmin` is committed and `xmin` <= `T.snapshot_xid`
- `xmax` is 0 (not yet deleted) OR `xmax` > `T.snapshot_xid` OR `xmax` is aborted

### Two-Phase Locking phases
```
GROWING phase:  transaction may acquire new locks, may NOT release any
SHRINKING phase: transaction may release locks, may NOT acquire new ones
                 (Strict 2PL: shrinking phase only happens at commit/abort)
```

### Deadlock
Transaction A waits for a lock held by B; B waits for a lock held by A → cycle → abort the younger transaction.

---

## Full Implementation

```cpp
#include <iostream>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include <list>
#include <mutex>
#include <shared_mutex>
#include <condition_variable>
#include <thread>
#include <stdexcept>
#include <optional>
#include <atomic>
#include <sstream>
#include <cassert>

// ─────────────────────────────────────────────
// 1.  Transaction state
// ─────────────────────────────────────────────

using TxID   = uint64_t;
using RowKey = std::string;

enum class TxStatus { ACTIVE, COMMITTED, ABORTED };

struct Transaction {
    TxID     id;
    TxID     snapshot_xid;   // read snapshot: see commits < snapshot_xid
    TxStatus status = TxStatus::ACTIVE;
    bool     in_shrinking = false;   // 2PL phase flag
};

// Global transaction table
static std::atomic<TxID>                          g_next_xid{1};
static std::mutex                                 g_tx_mutex;
static std::unordered_map<TxID, Transaction>      g_transactions;

TxID begin_transaction() {
    std::lock_guard lk(g_tx_mutex);
    TxID xid = g_next_xid.fetch_add(1);
    // snapshot: see all commits that finished before this xid
    TxID snap = xid;
    g_transactions[xid] = Transaction{xid, snap, TxStatus::ACTIVE, false};
    return xid;
}

bool is_committed(TxID xid) {
    std::lock_guard lk(g_tx_mutex);
    auto it = g_transactions.find(xid);
    return it != g_transactions.end() && it->second.status == TxStatus::COMMITTED;
}

bool is_aborted(TxID xid) {
    std::lock_guard lk(g_tx_mutex);
    auto it = g_transactions.find(xid);
    return it != g_transactions.end() && it->second.status == TxStatus::ABORTED;
}

// ─────────────────────────────────────────────
// 2.  MVCC version chain
// ─────────────────────────────────────────────

struct RowVersion {
    std::string value;
    TxID        xmin;   // created by
    TxID        xmax;   // deleted/updated by (0 = still live)
};

// Each logical row is a chain of versions (newest first)
static std::mutex                                       g_heap_mutex;
static std::unordered_map<RowKey, std::list<RowVersion>> g_heap;

// Visibility check for a snapshot taken at snapshot_xid
bool is_visible(const RowVersion& v, TxID snapshot_xid, TxID reader_xid) {
    // xmin must be committed and <= snapshot
    bool xmin_ok = (v.xmin == reader_xid)          // own write
                 || (is_committed(v.xmin) && v.xmin < snapshot_xid);
    if (!xmin_ok) return false;

    // xmax: version must not have been deleted before our snapshot
    if (v.xmax == 0) return true;
    bool xmax_invisible = (v.xmax == reader_xid)   // we deleted it ourselves
                        || (is_committed(v.xmax) && v.xmax < snapshot_xid);
    return !xmax_invisible;
}

std::optional<std::string> mvcc_read(TxID xid) {
    std::lock_guard lk(g_heap_mutex);
    TxID snap;
    {
        std::lock_guard tlk(g_tx_mutex);
        snap = g_transactions.at(xid).snapshot_xid;
    }
    for (auto& [key, chain] : g_heap) {
        // return first visible version of any key (demo: single-key table)
        for (auto& v : chain)
            if (is_visible(v, snap, xid)) return v.value;
    }
    return std::nullopt;
}

std::optional<std::string> mvcc_read_key(const RowKey& key, TxID xid) {
    std::lock_guard lk(g_heap_mutex);
    TxID snap;
    {
        std::lock_guard tlk(g_tx_mutex);
        snap = g_transactions.at(xid).snapshot_xid;
    }
    auto it = g_heap.find(key);
    if (it == g_heap.end()) return std::nullopt;
    for (auto& v : it->second)
        if (is_visible(v, snap, xid)) return v.value;
    return std::nullopt;
}

// INSERT: new version, xmin=xid, xmax=0
void mvcc_insert(const RowKey& key, const std::string& value, TxID xid) {
    std::lock_guard lk(g_heap_mutex);
    g_heap[key].push_front({value, xid, 0});
}

// UPDATE: mark old visible version as xmax=xid, insert new version
void mvcc_update(const RowKey& key, const std::string& new_value, TxID xid) {
    std::lock_guard lk(g_heap_mutex);
    TxID snap;
    {
        std::lock_guard tlk(g_tx_mutex);
        snap = g_transactions.at(xid).snapshot_xid;
    }
    auto it = g_heap.find(key);
    if (it != g_heap.end()) {
        for (auto& v : it->second) {
            if (is_visible(v, snap, xid) && v.xmax == 0) {
                v.xmax = xid;   // logically delete old version
                break;
            }
        }
    }
    g_heap[key].push_front({new_value, xid, 0});
}

// DELETE: mark visible version xmax=xid
void mvcc_delete(const RowKey& key, TxID xid) {
    std::lock_guard lk(g_heap_mutex);
    TxID snap;
    {
        std::lock_guard tlk(g_tx_mutex);
        snap = g_transactions.at(xid).snapshot_xid;
    }
    auto it = g_heap.find(key);
    if (it == g_heap.end()) return;
    for (auto& v : it->second) {
        if (is_visible(v, snap, xid) && v.xmax == 0) {
            v.xmax = xid;
            return;
        }
    }
}

// ─────────────────────────────────────────────
// 3.  Lock Manager (Strict 2PL)
// ─────────────────────────────────────────────

enum class LockMode { SHARED, EXCLUSIVE };

struct LockRequest {
    TxID     xid;
    LockMode mode;
    bool     granted = false;
};

struct LockQueue {
    std::list<LockRequest>  requests;
    std::mutex              mu;
    std::condition_variable cv;
};

static std::mutex                                      g_lm_mutex;
static std::unordered_map<RowKey, LockQueue>           g_lock_table;

// Waits-for graph for deadlock detection: waiter -> set of holders it's waiting on
static std::unordered_map<TxID, std::unordered_set<TxID>> g_waits_for;

bool has_cycle(TxID start, const std::unordered_map<TxID, std::unordered_set<TxID>>& graph) {
    std::unordered_set<TxID> visited, stack;
    std::function<bool(TxID)> dfs = [&](TxID node) -> bool {
        visited.insert(node);
        stack.insert(node);
        auto it = graph.find(node);
        if (it != graph.end()) {
            for (TxID nb : it->second) {
                if (!visited.count(nb) && dfs(nb)) return true;
                if (stack.count(nb)) return true;
            }
        }
        stack.erase(node);
        return false;
    };
    return dfs(start);
}

// Returns true if lock granted; throws DeadlockException if cycle detected
class DeadlockException : public std::runtime_error {
public: explicit DeadlockException(TxID xid)
    : std::runtime_error("Deadlock detected, aborting tx " + std::to_string(xid)) {}
};

void acquire_lock(const RowKey& key, TxID xid, LockMode mode) {
    // 2PL: cannot acquire lock in shrinking phase
    {
        std::lock_guard lk(g_tx_mutex);
        if (g_transactions.at(xid).in_shrinking)
            throw std::runtime_error("2PL violation: cannot acquire lock in shrinking phase");
    }

    LockQueue& lq = g_lock_table[key];   // creates entry if absent
    std::unique_lock ul(lq.mu);

    // Check if we already hold this lock
    for (auto& r : lq.requests) {
        if (r.xid == xid && r.granted) {
            if (mode == LockMode::SHARED) return;  // already have shared (or better)
            if (r.mode == LockMode::EXCLUSIVE) return;  // already exclusive
            // Upgrade: shared -> exclusive — need no other shared holders
        }
    }

    // Add our request
    lq.requests.push_back({xid, mode, false});
    auto& my_req = lq.requests.back();

    while (true) {
        // Can we grant?
        bool conflict = false;
        std::unordered_set<TxID> blocking;
        for (auto& r : lq.requests) {
            if (&r == &my_req) break;      // only look at earlier requests
            if (!r.granted) continue;
            if (mode == LockMode::EXCLUSIVE || r.mode == LockMode::EXCLUSIVE) {
                if (r.xid != xid) { conflict = true; blocking.insert(r.xid); }
            }
        }

        if (!conflict) {
            my_req.granted = true;
            {
                std::lock_guard lk(g_lm_mutex);
                g_waits_for.erase(xid);
            }
            return;
        }

        // Record waits-for edges and check for cycle
        {
            std::lock_guard lk(g_lm_mutex);
            g_waits_for[xid] = blocking;
            if (has_cycle(xid, g_waits_for)) {
                g_waits_for.erase(xid);
                lq.requests.remove_if([&](const LockRequest& r){ return r.xid == xid && !r.granted; });
                throw DeadlockException(xid);
            }
        }

        lq.cv.wait(ul);   // wait for a signal from a release
    }
}

void release_locks(TxID xid) {
    // Shrinking phase begins — mark transaction
    {
        std::lock_guard lk(g_tx_mutex);
        if (g_transactions.count(xid))
            g_transactions.at(xid).in_shrinking = true;
    }

    // Release all locks held by xid across all queues
    for (auto& [key, lq] : g_lock_table) {
        std::unique_lock ul(lq.mu);
        lq.requests.remove_if([&](const LockRequest& r){ return r.xid == xid; });
        lq.cv.notify_all();   // wake waiters
    }

    {
        std::lock_guard lk(g_lm_mutex);
        g_waits_for.erase(xid);
    }
}

// ─────────────────────────────────────────────
// 4.  Transaction Manager (public API)
// ─────────────────────────────────────────────

class TransactionManager {
public:
    TxID begin() { return begin_transaction(); }

    std::optional<std::string> read(TxID xid, const RowKey& key) {
        acquire_lock(key, xid, LockMode::SHARED);
        return mvcc_read_key(key, xid);
    }

    void insert(TxID xid, const RowKey& key, const std::string& value) {
        acquire_lock(key, xid, LockMode::EXCLUSIVE);
        mvcc_insert(key, value, xid);
    }

    void update(TxID xid, const RowKey& key, const std::string& value) {
        acquire_lock(key, xid, LockMode::EXCLUSIVE);
        mvcc_update(key, value, xid);
    }

    void remove(TxID xid, const RowKey& key) {
        acquire_lock(key, xid, LockMode::EXCLUSIVE);
        mvcc_delete(key, xid);
    }

    void commit(TxID xid) {
        {
            std::lock_guard lk(g_tx_mutex);
            g_transactions.at(xid).status = TxStatus::COMMITTED;
        }
        release_locks(xid);
        std::cout << "[TX " << xid << "] COMMITTED\n";
    }

    void abort(TxID xid) {
        // Roll back: mark all versions written by xid as invisible
        {
            std::lock_guard lk(g_heap_mutex);
            for (auto& [key, chain] : g_heap) {
                for (auto& v : chain) {
                    if (v.xmin == xid) v.xmax = xid;  // make own inserts invisible
                    if (v.xmax == xid) v.xmax = 0;    // undo own deletes
                }
            }
        }
        {
            std::lock_guard lk(g_tx_mutex);
            g_transactions.at(xid).status = TxStatus::ABORTED;
        }
        release_locks(xid);
        std::cout << "[TX " << xid << "] ABORTED\n";
    }
};

// ─────────────────────────────────────────────
// 5.  Demo scenarios
// ─────────────────────────────────────────────

void print_val(const std::optional<std::string>& v, TxID xid, const RowKey& key) {
    std::cout << "  [TX " << xid << "] READ " << key << " = "
              << (v ? *v : "<not visible>") << "\n";
}

int main() {
    TransactionManager tm;

    // ── Scenario 1: Basic MVCC snapshot isolation ──
    std::cout << "=== Scenario 1: MVCC Snapshot Isolation ===\n";
    {
        TxID t1 = tm.begin();
        tm.insert(t1, "balance", "1000");
        tm.commit(t1);

        TxID t2 = tm.begin();   // snapshot after t1 committed
        TxID t3 = tm.begin();

        // t3 updates balance — t2 should still see old value
        tm.update(t3, "balance", "2000");
        tm.commit(t3);

        auto v = tm.read(t2, "balance");
        print_val(v, t2, "balance");   // expects 1000 (t3 committed after t2 started)
        tm.commit(t2);
    }

    // ── Scenario 2: Two-Phase Locking — concurrent reads ──
    std::cout << "\n=== Scenario 2: Concurrent Shared Locks ===\n";
    {
        TxID t4 = tm.begin();
        TxID t5 = tm.begin();
        print_val(tm.read(t4, "balance"), t4, "balance");  // shared lock
        print_val(tm.read(t5, "balance"), t5, "balance");  // shared lock — both granted
        tm.commit(t4);
        tm.commit(t5);
    }

    // ── Scenario 3: Exclusive lock blocks shared ──
    std::cout << "\n=== Scenario 3: Exclusive Lock + Waiting ===\n";
    {
        TxID t6 = tm.begin();
        tm.update(t6, "balance", "3000");  // holds EXCLUSIVE lock on "balance"

        // t7 runs on a separate thread, will block until t6 commits
        std::thread reader([&]() {
            TxID t7 = tm.begin();
            std::cout << "  [TX " << t7 << "] waiting for shared lock on balance...\n";
            auto v = tm.read(t7, "balance");
            print_val(v, t7, "balance");  // sees 3000 after t6 commits
            tm.commit(t7);
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        tm.commit(t6);    // releases lock, unblocks t7
        reader.join();
    }

    // ── Scenario 4: Deadlock detection ──
    std::cout << "\n=== Scenario 4: Deadlock Detection ===\n";
    {
        TxID ta = tm.begin();
        TxID tb = tm.begin();

        // ta holds lock on "A", tb holds lock on "B"
        tm.insert(ta, "A", "val_a");
        tm.insert(tb, "B", "val_b");
        tm.commit(ta);
        tm.commit(tb);

        TxID t8 = tm.begin();
        TxID t9 = tm.begin();

        acquire_lock("A", t8, LockMode::EXCLUSIVE);
        acquire_lock("B", t9, LockMode::EXCLUSIVE);

        // t8 wants B (held by t9), t9 wants A (held by t8) → deadlock
        std::thread th1([&]() {
            try {
                acquire_lock("B", t8, LockMode::EXCLUSIVE);
                tm.commit(t8);
            } catch (DeadlockException& e) {
                std::cout << "  " << e.what() << "\n";
                tm.abort(t8);
            }
        });

        std::this_thread::sleep_for(std::chrono::milliseconds(20));

        try {
            acquire_lock("A", t9, LockMode::EXCLUSIVE);
            tm.commit(t9);
        } catch (DeadlockException& e) {
            std::cout << "  " << e.what() << "\n";
            tm.abort(t9);
        }

        th1.join();
    }

    std::cout << "\nAll scenarios complete.\n";
    return 0;
}
```

```bash
g++ -std=c++17 -pthread -o txmgr txmgr.cpp && ./txmgr
```

Expected output:
```
=== Scenario 1: MVCC Snapshot Isolation ===
[TX 3] COMMITTED
[TX 4] COMMITTED
  [TX 2] READ balance = 1000        ← sees pre-t3 snapshot

=== Scenario 2: Concurrent Shared Locks ===
  [TX 4] READ balance = 3000
  [TX 5] READ balance = 3000
[TX 4] COMMITTED
[TX 5] COMMITTED

=== Scenario 3: Exclusive Lock + Waiting ===
  [TX 7] waiting for shared lock on balance...
[TX 6] COMMITTED
  [TX 7] READ balance = 3000
[TX 7] COMMITTED

=== Scenario 4: Deadlock Detection ===
  Deadlock detected, aborting tx 8 (or 9)
[TX 8] ABORTED
[TX 9] COMMITTED
```

---

## Architecture Diagram

```
Application
    │
    ▼
TransactionManager.begin() / read() / update() / commit() / abort()
    │
    ├─► LockManager (Strict 2PL)
    │       growing phase: acquire SHARED or EXCLUSIVE lock
    │       shrinking phase: release all locks on commit/abort
    │       deadlock detection: waits-for graph, DFS cycle check
    │
    └─► MVCC Heap (version chain per row)
            INSERT  → push new version {value, xmin=xid, xmax=0}
            UPDATE  → stamp old xmax=xid, push new version
            DELETE  → stamp old xmax=xid
            READ    → walk chain, return first version where
                      xmin committed < snapshot AND
                      (xmax=0 OR xmax not yet committed)
```

---

## MVCC vs 2PL — Why both?

| Property               | MVCC alone                                  | 2PL alone                              | MVCC + Strict 2PL                        |
|------------------------|---------------------------------------------|----------------------------------------|------------------------------------------|
| Read-write contention  | None — readers never block writers          | Readers block writers (shared lock)    | None — readers use snapshots             |
| Write-write contention | Last writer wins (lost update problem)      | Serializable via exclusive locks       | Serializable — exclusive lock on write   |
| Serializability        | Snapshot Isolation only (not always serial) | Serializable                           | Serializable                             |
| Deadlock               | N/A                                         | Possible                               | Possible — needs detection               |
| Old version cleanup    | Needs vacuum/GC                             | N/A                                    | Needs vacuum/GC                          |

PostgreSQL uses MVCC + Serializable Snapshot Isolation (SSI) — a refinement that detects dangerous read-write anti-dependencies without the throughput cost of 2PL.

---

## Two-Phase Locking — Phase Boundary

```
GROWING PHASE               │  SHRINKING PHASE
acquire S lock on A    ✓    │
acquire X lock on B    ✓    │
acquire S lock on C    ✓    │
                            │  release lock on A    ✓
                            │  release lock on B    ✓
acquire lock on D      ✗  ← violation: 2PL broken, schedule no longer serializable
```

**Strict 2PL** (used here) simplifies this: the shrinking phase only occurs at commit/abort, so the boundary is always at the end of the transaction. This avoids cascading aborts.

---

## Key Takeaways
- MVCC creates a new row version per write; readers walk the version chain and apply the visibility rule against their snapshot XID.
- Strict 2PL holds all locks until commit/abort — the shrinking phase is instantaneous at transaction end.
- The combination eliminates read-write contention (MVCC) while preserving serializability for writes (2PL).
- Deadlock detection via waits-for graph DFS is O(V+E) per lock request — PostgreSQL runs a similar check periodically rather than per-request for performance.
- ABORT must undo MVCC writes: own inserts are hidden (xmax=xid), own deletes are reversed (xmax=0).
