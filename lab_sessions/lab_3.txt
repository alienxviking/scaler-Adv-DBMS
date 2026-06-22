# Lab Session 3: Clock Sweep Page Replacement Algorithm in C++

## Objective
Implement the ClockSweep (Clock) buffer pool page replacement algorithm used in PostgreSQL's buffer manager. Understand how it approximates LRU without the overhead of maintaining an ordered list.

---

## Background

PostgreSQL uses ClockSweep (not LRU) to evict pages from its shared buffer pool. Each buffer frame carries a `usage_count` (0–5). The "clock hand" sweeps through frames in a circular fashion:
- If `usage_count > 0`: decrement and move on (the page got a "second chance").
- If `usage_count == 0` and frame is not pinned: evict this frame.

Every time a page is accessed, its `usage_count` is incremented (capped at 5 in PostgreSQL).

---

## Implementation

```cpp
#include <iostream>
#include <vector>
#include <unordered_map>
#include <string>

struct Frame {
    int     page_id    = -1;   // -1 = empty
    int     usage_count = 0;
    bool    pinned     = false;
};

class BufferPool {
    std::vector<Frame>              frames;
    std::unordered_map<int,int>     page_to_frame;  // page_id -> frame index
    int                             hand = 0;        // clock hand
    int                             capacity;

public:
    explicit BufferPool(int cap) : frames(cap), capacity(cap) {}

    // Pin a page into the buffer pool (load if not present).
    // Returns frame index, or -1 if all frames are pinned.
    int fetch(int page_id) {
        // Already in pool
        auto it = page_to_frame.find(page_id);
        if (it != page_to_frame.end()) {
            int idx = it->second;
            frames[idx].usage_count = std::min(frames[idx].usage_count + 1, 5);
            std::cout << "[HIT]  page " << page_id
                      << " in frame " << idx
                      << " usage=" << frames[idx].usage_count << "\n";
            return idx;
        }

        // Find a victim via ClockSweep
        int victim = clocksweep();
        if (victim == -1) {
            std::cerr << "[ERR]  all frames pinned, cannot evict\n";
            return -1;
        }

        // Evict current occupant
        if (frames[victim].page_id != -1) {
            std::cout << "[EVICT] page " << frames[victim].page_id
                      << " from frame " << victim << "\n";
            page_to_frame.erase(frames[victim].page_id);
        }

        // Load new page
        frames[victim] = {page_id, 1, false};
        page_to_frame[page_id] = victim;
        std::cout << "[MISS] page " << page_id
                  << " loaded into frame " << victim << "\n";
        return victim;
    }

    void pin(int page_id) {
        auto it = page_to_frame.find(page_id);
        if (it != page_to_frame.end()) frames[it->second].pinned = true;
    }

    void unpin(int page_id) {
        auto it = page_to_frame.find(page_id);
        if (it != page_to_frame.end()) frames[it->second].pinned = false;
    }

    void print_state() const {
        std::cout << "\n--- Buffer Pool State (hand=" << hand << ") ---\n";
        for (int i = 0; i < capacity; i++) {
            const auto& f = frames[i];
            std::cout << "Frame[" << i << "] page="
                      << (f.page_id == -1 ? std::string("--") : std::to_string(f.page_id))
                      << " usage=" << f.usage_count
                      << (f.pinned ? " [PINNED]" : "")
                      << (i == hand ? " <-- hand" : "")
                      << "\n";
        }
        std::cout << "-------------------------------\n\n";
    }

private:
    // Returns the index of the frame to evict.
    int clocksweep() {
        int checked = 0;
        while (checked < 2 * capacity) {   // two full sweeps max
            Frame& f = frames[hand];
            if (!f.pinned) {
                if (f.usage_count == 0) {
                    int victim = hand;
                    hand = (hand + 1) % capacity;
                    return victim;
                }
                f.usage_count--;
            }
            hand = (hand + 1) % capacity;
            checked++;
        }
        return -1; // all pinned
    }
};

int main() {
    BufferPool pool(4);   // 4 frame buffer pool

    // Simulate page access pattern
    std::vector<int> accesses = {1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5};

    for (int page : accesses) {
        pool.fetch(page);
    }
    pool.print_state();

    return 0;
}
```

Compile and run:
```bash
g++ -std=c++17 -o clocksweep clocksweep.cpp
./clocksweep
```

---

## Trace of the algorithm

For a 4-frame pool with access sequence `1 2 3 4 1 2 5`:

```
MISS  page 1 -> frame 0  usage=1
MISS  page 2 -> frame 1  usage=1
MISS  page 3 -> frame 2  usage=1
MISS  page 4 -> frame 3  usage=1
HIT   page 1 -> frame 0  usage=2   (hand sweeps, won't evict usage>0)
HIT   page 2 -> frame 1  usage=2
MISS  page 5 -> ClockSweep starts at hand:
        frame 0: usage=2 -> decrement to 1, skip
        frame 1: usage=2 -> decrement to 1, skip
        frame 2: usage=1 -> decrement to 0, skip
        frame 3: usage=1 -> decrement to 0, skip
        frame 0: usage=1 -> decrement to 0, skip
        ...eventually evicts the frame that hits 0 first
```

Pages 1 and 2 survive longer because of their higher usage count — ClockSweep approximates LRU without a sorted structure.

---

## Why PostgreSQL uses ClockSweep over LRU

| Property              | LRU                          | ClockSweep                        |
|-----------------------|------------------------------|-----------------------------------|
| Eviction quality      | Optimal (exact recency)      | Near-optimal (approximate recency)|
| Data structure        | Doubly-linked list + hashmap | Circular array                    |
| Time per access       | O(1) but with lock contention| O(1), lock-free on usage_count    |
| Sequential scan flood | Wrecks LRU (all pages evict) | Usage count caps at 5, limits damage|

The `usage_count` cap also provides natural protection against sequential scan flooding — a full table scan increments each page's count by 1, so hot pages (count=5) survive the sweep.

---

## Key Takeaways
- ClockSweep trades perfect recency tracking for lower overhead and lock contention.
- The circular hand means no expensive list maintenance on every page access.
- `usage_count` (not a single reference bit) gives finer-grained "hotness" tracking.
- This is the exact algorithm in `src/backend/storage/buffer/freelist.c` in the PostgreSQL source.
