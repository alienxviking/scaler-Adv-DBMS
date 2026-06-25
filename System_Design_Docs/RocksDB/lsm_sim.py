"""
Minimal LSM-tree compaction simulator.

Goal: produce *real* write-amplification (WA) and space-amplification (SA)
numbers for two classic compaction strategies, to illustrate the core
RocksDB trade-off. This is a behavioural model (not byte-accurate RocksDB),
but it faithfully reproduces the multiplicative-rewrite mechanism that makes
WA and SA diverge between strategies.

Conventions:
- 1 record = 1 unit of "bytes".
- bytes_written counts every record physically written to an SSTable
  (flushes + every rewrite during compaction). User ingests `n_ops` records.
- WA = bytes_written / n_ops        (lower is better for write-heavy)
- SA = live_bytes_on_disk / unique_live_keys  (1.0 = perfect, higher = waste)
"""
import random

random.seed(42)  # deterministic, reproducible run

MEMTABLE = 1_000          # records per memtable flush -> one L0 SSTable
L0_TRIGGER = 4            # # L0 files that triggers compaction into L1
FANOUT = 10               # T: each level ~10x the previous (leveled)
SIZE_TIERED_RUN = 4       # # similarly-sized runs merged together (tiered)


def make_workload(n_ops, key_space):
    """n_ops writes over key_space distinct keys (smaller key_space => more overwrites)."""
    return [random.randrange(key_space) for _ in range(n_ops)]


def merge(*runs):
    """Merge runs keeping the LAST value per key (newest wins). Returns dict key->val."""
    out = {}
    for r in runs:          # earliest first, latest last so newest overwrites
        out.update(r)
    return out


def leveled(ops):
    """RocksDB-style leveled compaction: each level kept fully sorted, dedup'd, capped."""
    bytes_written = 0
    mem = {}
    L0 = []                      # list of dicts (overlapping runs)
    levels = {}                  # level_idx (>=1) -> single dict (non-overlapping)
    def cap(i):                  # capacity of level i in records
        return MEMTABLE * L0_TRIGGER * (FANOUT ** (i - 1))

    def flush():
        nonlocal bytes_written, mem
        if not mem:
            return
        bytes_written += len(mem)            # write the L0 SSTable
        L0.append(mem)
        mem = {}

    def compact_L0():
        nonlocal bytes_written
        merged = merge(levels.get(1, {}), *L0)   # fold all L0 into L1
        L0.clear()
        levels[1] = merged
        bytes_written += len(merged)             # rewrite the new L1
        cascade(1)

    def cascade(i):
        nonlocal bytes_written
        while len(levels.get(i, {})) > cap(i):
            nxt = merge(levels.get(i + 1, {}), levels[i])  # push level i down into i+1
            levels[i + 1] = nxt
            levels[i] = {}
            bytes_written += len(nxt)                      # rewrite level i+1
            i += 1

    for k in ops:
        mem[k] = k
        if len(mem) >= MEMTABLE:
            flush()
            if len(L0) >= L0_TRIGGER:
                compact_L0()

    flush()
    if L0:
        compact_L0()

    live = merge(*([levels[i] for i in sorted(levels)] + L0 + [mem]))
    live_bytes = sum(len(v) for v in [*L0, mem]) + sum(len(levels[i]) for i in levels)
    return bytes_written, len(live), live_bytes


def size_tiered(ops):
    """Cassandra-style size-tiered: accumulate same-size runs, merge when SIZE_TIERED_RUN pile up."""
    bytes_written = 0
    mem = {}
    tiers = {}   # size-class -> list of runs (dicts) of roughly that size

    def flush():
        nonlocal bytes_written, mem
        if not mem:
            return
        bytes_written += len(mem)
        tiers.setdefault(0, []).append(mem)
        mem = {}
        compact()

    def compact():
        nonlocal bytes_written
        cls = 0
        while len(tiers.get(cls, [])) >= SIZE_TIERED_RUN:
            runs = tiers.pop(cls)
            merged = merge(*runs)
            bytes_written += len(merged)            # rewrite the merged run
            tiers.setdefault(cls + 1, []).append(merged)
            cls += 1

    for k in ops:
        mem[k] = k
        if len(mem) >= MEMTABLE:
            flush()
    flush()

    all_runs = [r for rs in tiers.values() for r in rs] + [mem]
    live = merge(*all_runs)
    live_bytes = sum(len(r) for r in all_runs)   # duplicates across runs still occupy disk
    return bytes_written, len(live), live_bytes


def report(name, ops):
    n = len(ops)
    print(f"\n## {name}  (n_ops={n:,}, distinct keys touched={len(set(ops)):,})")
    for label, fn in (("Leveled", leveled), ("Size-tiered", size_tiered)):
        bw, live_keys, live_bytes = fn(list(ops))
        wa = bw / n
        sa = live_bytes / live_keys
        print(f"  {label:12s}  write-amp={wa:5.2f}x   space-amp={sa:5.2f}x   "
              f"(phys written={bw:,}, live keys={live_keys:,}, on-disk={live_bytes:,})")


if __name__ == "__main__":
    # Update-heavy: 200k ops over only 20k keys -> 10x overwrite => space-amp matters
    report("Update-heavy workload (200k ops / 20k keys)", make_workload(200_000, 20_000))
    # Mostly-unique inserts: 200k ops over 200k keys -> write-amp dominates
    report("Insert-heavy workload (200k ops / 200k keys)", make_workload(200_000, 200_000))
