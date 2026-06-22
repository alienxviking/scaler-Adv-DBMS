# Lab Session 3: Clock Sweep Page Replacement Algorithm in C++

**Name:** Snehangshu Roy
**Roll No:** 24BCS10155

## Objective
Implement the ClockSweep (Clock) buffer-pool page replacement algorithm used in
PostgreSQL's buffer manager, and understand how it approximates LRU without the
overhead of maintaining an ordered list.

## Files
- `clocksweep.cpp` — buffer pool with ClockSweep eviction.
- `makefile` — build / run.

## Build & Run
```bash
make
make run
# or
g++ -std=c++17 -o clocksweep clocksweep.cpp && ./clocksweep
```

## Background
Each buffer frame carries a `usage_count` (0–5). The clock hand sweeps frames
circularly:
- `usage_count > 0` → decrement and move on (a "second chance").
- `usage_count == 0` and not pinned → evict this frame.

Every access increments `usage_count` (capped at 5).

## Trace (4-frame pool, sequence `1 2 3 4 1 2 5`)
```
MISS  page 1 -> frame 0  usage=1
MISS  page 2 -> frame 1  usage=1
MISS  page 3 -> frame 2  usage=1
MISS  page 4 -> frame 3  usage=1
HIT   page 1            usage=2
HIT   page 2            usage=2
MISS  page 5 -> ClockSweep decrements usage on each frame until one hits 0, then evicts it
```
Pages 1 and 2 survive longer because of their higher usage count — ClockSweep
approximates LRU without a sorted structure.

## Why PostgreSQL uses ClockSweep over LRU

| Property              | LRU                          | ClockSweep                          |
|-----------------------|------------------------------|-------------------------------------|
| Eviction quality      | Optimal (exact recency)      | Near-optimal (approximate recency)  |
| Data structure        | Doubly-linked list + hashmap | Circular array                      |
| Time per access       | O(1) but lock contention     | O(1), lock-free on usage_count      |
| Sequential scan flood | Wrecks LRU (all pages evict) | usage_count cap limits damage       |

The `usage_count` cap also protects against sequential-scan flooding: a full
table scan bumps each page by 1, so hot pages (count=5) survive the sweep.

## Key Takeaways
- ClockSweep trades perfect recency tracking for lower overhead and lock contention.
- The circular hand means no expensive list maintenance on every access.
- `usage_count` (not a single reference bit) gives finer-grained "hotness" tracking.
- This is the algorithm in `src/backend/storage/buffer/freelist.c` in PostgreSQL.
