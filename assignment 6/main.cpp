#include <iostream>
#include <vector>
#include <unordered_map>
#include <optional>
#include <string>

// Clock Sweep Buffer Replacement Policy
// ─────────────────────────────────────────────
// Each frame in the buffer pool has:
//   - key: the page/block identifier
//   - value: the cached data
//   - refBit: set to 1 on access; clock hand skips frames with refBit=1 (clearing it)
//
// On eviction the clock hand sweeps circularly:
//   if refBit == 1 → clear it, advance
//   if refBit == 0 → evict this frame

template <typename Key, typename Value>
class ClockSweep {
public:
  ClockSweep(int maxSize) : maxCacheSize(maxSize), clockHand(0) {
    frames.reserve(maxSize);
  }

  // ─── GET: look up a key in the buffer ───
  std::optional<Value> get(Key key) {
    auto it = pageTable.find(key);
    if (it != pageTable.end()) {
      // HIT: set reference bit
      int idx = it->second;
      frames[idx].refBit = true;
      std::cout << "  [HIT]  key=" << key << " at frame " << idx << "\n";
      return frames[idx].value;
    }
    // MISS
    std::cout << "  [MISS] key=" << key << "\n";
    return std::nullopt;
  }

  // ─── PUT: insert or update a key/value in the buffer ───
  void put(Key key, Value value) {
    // If key already in buffer, update in place
    auto it = pageTable.find(key);
    if (it != pageTable.end()) {
      int idx = it->second;
      frames[idx].value = value;
      frames[idx].refBit = true;
      std::cout << "  [UPDATE] key=" << key << " at frame " << idx << "\n";
      return;
    }

    // If buffer is not yet full, append
    if ((int)frames.size() < maxCacheSize) {
      int idx = (int)frames.size();
      frames.push_back(Frame{key, value, true});
      pageTable[key] = idx;
      std::cout << "  [LOAD]  key=" << key << " into frame " << idx << "\n";
      return;
    }

    // Buffer is full — run clock sweep to find a victim
    evictAndInsert(key, value);
  }

  // ─── Print buffer state ───
  void printBuffer() {
    std::cout << "  Buffer [hand=" << clockHand << "]: ";
    for (int i = 0; i < (int)frames.size(); i++) {
      std::cout << "(" << frames[i].key << ",ref=" << frames[i].refBit << ") ";
    }
    std::cout << "\n";
  }

private:
  struct Frame {
    Key key;
    Value value;
    bool refBit;
  };

  int maxCacheSize;
  int clockHand;
  std::vector<Frame> frames;
  std::unordered_map<Key, int> pageTable; // key → frame index

  // ─── Clock sweep eviction ───
  void evictAndInsert(Key key, Value value) {
    while (true) {
      Frame &f = frames[clockHand];
      if (f.refBit) {
        // Give a second chance — clear the bit and move on
        f.refBit = false;
        clockHand = (clockHand + 1) % maxCacheSize;
      } else {
        // Evict this frame
        std::cout << "  [EVICT] frame " << clockHand << " (key=" << f.key
                  << ") → replacing with key=" << key << "\n";
        pageTable.erase(f.key);

        f.key = key;
        f.value = value;
        f.refBit = true;
        pageTable[key] = clockHand;

        clockHand = (clockHand + 1) % maxCacheSize;
        return;
      }
    }
  }
};

// ─── Main: Demo Driver ───
int main() {
  std::cout << "===== Clock Sweep Buffer Replacement Demo =====\n";
  std::cout << "Buffer size = 4 frames\n\n";

  ClockSweep<int, std::string> buffer(4);

  // Load 4 pages — fills the buffer
  std::cout << "--- Loading pages 1..4 ---\n";
  buffer.put(1, "Page_1_data");
  buffer.put(2, "Page_2_data");
  buffer.put(3, "Page_3_data");
  buffer.put(4, "Page_4_data");
  buffer.printBuffer();

  // Access page 1 and 3 (sets their ref bits)
  std::cout << "\n--- Accessing pages 1 and 3 ---\n";
  buffer.get(1);
  buffer.get(3);
  buffer.printBuffer();

  // Insert page 5 — buffer full, clock sweep starts
  // All ref bits are 1 initially; sweep will clear them until it finds refBit=0
  std::cout << "\n--- Inserting page 5 (triggers eviction) ---\n";
  buffer.put(5, "Page_5_data");
  buffer.printBuffer();

  // Insert page 6 — another eviction
  std::cout << "\n--- Inserting page 6 (triggers eviction) ---\n";
  buffer.put(6, "Page_6_data");
  buffer.printBuffer();

  // Search for evicted and present keys
  std::cout << "\n--- Searching ---\n";
  buffer.get(2); // should be evicted
  buffer.get(5); // should be present
  buffer.get(1); // depends on eviction

  // Insert page 7
  std::cout << "\n--- Inserting page 7 ---\n";
  buffer.put(7, "Page_7_data");
  buffer.printBuffer();

  // Final state
  std::cout << "\n--- Final buffer state ---\n";
  buffer.printBuffer();

  return 0;
}
