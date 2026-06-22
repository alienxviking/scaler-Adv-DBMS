// Lab Session 3: Clock Sweep Page Replacement Algorithm in C++
//
// Implements the ClockSweep (Clock) buffer-pool page replacement algorithm used
// in PostgreSQL's buffer manager (src/backend/storage/buffer/freelist.c). It
// approximates LRU without maintaining an ordered list: each frame carries a
// usage_count (0..5) and a circular "clock hand" sweeps for a victim.
//
// Build:  g++ -std=c++17 -Wall -Wextra -O2 -o clocksweep clocksweep.cpp
// Run:    ./clocksweep

#include <iostream>
#include <vector>
#include <unordered_map>
#include <string>
#include <algorithm>

struct Frame {
    int  page_id     = -1;   // -1 = empty
    int  usage_count = 0;
    bool pinned      = false;
};

class BufferPool {
    std::vector<Frame>          frames;
    std::unordered_map<int,int> page_to_frame;  // page_id -> frame index
    int                         hand = 0;        // clock hand
    int                         capacity;

public:
    explicit BufferPool(int cap) : frames(cap), capacity(cap) {}

    // Pin a page into the buffer pool (load if not present).
    // Returns frame index, or -1 if all frames are pinned.
    int fetch(int page_id) {
        auto it = page_to_frame.find(page_id);
        if (it != page_to_frame.end()) {                 // already resident
            int idx = it->second;
            frames[idx].usage_count = std::min(frames[idx].usage_count + 1, 5);
            std::cout << "[HIT]   page " << page_id
                      << " in frame " << idx
                      << " usage=" << frames[idx].usage_count << "\n";
            return idx;
        }

        int victim = clocksweep();
        if (victim == -1) {
            std::cerr << "[ERR]   all frames pinned, cannot evict\n";
            return -1;
        }

        if (frames[victim].page_id != -1) {              // evict current occupant
            std::cout << "[EVICT] page " << frames[victim].page_id
                      << " from frame " << victim << "\n";
            page_to_frame.erase(frames[victim].page_id);
        }

        frames[victim] = {page_id, 1, false};            // load new page
        page_to_frame[page_id] = victim;
        std::cout << "[MISS]  page " << page_id
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
    // Returns the index of the frame to evict (-1 if all pinned).
    int clocksweep() {
        int checked = 0;
        while (checked < 2 * capacity) {   // at most two full sweeps
            Frame& f = frames[hand];
            if (!f.pinned) {
                if (f.usage_count == 0) {
                    int victim = hand;
                    hand = (hand + 1) % capacity;
                    return victim;
                }
                f.usage_count--;           // second chance
            }
            hand = (hand + 1) % capacity;
            checked++;
        }
        return -1;
    }
};

int main() {
    BufferPool pool(4);   // 4-frame buffer pool

    std::vector<int> accesses = {1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5};
    for (int page : accesses)
        pool.fetch(page);

    pool.print_state();
    return 0;
}
