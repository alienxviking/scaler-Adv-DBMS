"""Lock manager implementing strict two-phase locking (2PL).

Locks are taken on named resources (MiniDB locks at table granularity, e.g.
``"table:users"``, which is enough to guarantee serializability and prevent
phantoms). Two modes are supported:

    S (shared)     many readers may hold it together
    X (exclusive)  a single writer, incompatible with S and X

Under **strict** 2PL all locks are held until the transaction commits or
aborts (release is driven by the transaction manager), so schedules are
serializable and recoverable.

Lock waits can form cycles, so before a transaction blocks we add it to a
*waits-for* graph and run cycle detection; if a cycle is found the requester
is chosen as the deadlock victim and a ``DeadlockError`` is raised so the
engine can abort and (optionally) retry it.
"""

from __future__ import annotations

import threading
from enum import Enum
from typing import Dict, List, Set


class LockMode(Enum):
    S = "S"
    X = "X"


class DeadlockError(Exception):
    """Raised when granting a lock would close a cycle in the waits-for graph."""


class _ResourceLock:
    __slots__ = ("holders", "waiters")

    def __init__(self) -> None:
        self.holders: Dict[int, LockMode] = {}   # txn_id -> mode
        self.waiters: List[int] = []              # txn_ids waiting, in order


class LockManager:
    def __init__(self) -> None:
        self._mutex = threading.Lock()
        self._cv = threading.Condition(self._mutex)
        self._resources: Dict[str, _ResourceLock] = {}
        # Wait-for graph: txn -> set of txns it is currently waiting on.
        self._waits_for: Dict[int, Set[int]] = {}
        # What each txn holds, for release and reporting.
        self._held: Dict[int, Dict[str, LockMode]] = {}

    # -- compatibility ------------------------------------------------------
    def _compatible(self, res: _ResourceLock, txn_id: int, mode: LockMode) -> bool:
        for holder, held_mode in res.holders.items():
            if holder == txn_id:
                continue
            if mode is LockMode.X or held_mode is LockMode.X:
                return False
        return True

    def _conflicting_holders(self, res: _ResourceLock, txn_id: int,
                             mode: LockMode) -> Set[int]:
        out = set()
        for holder, held_mode in res.holders.items():
            if holder == txn_id:
                continue
            if mode is LockMode.X or held_mode is LockMode.X:
                out.add(holder)
        return out

    def _has_cycle(self, start: int) -> bool:
        """DFS from *start* over the waits-for graph looking for a cycle."""
        stack = [start]
        seen: Set[int] = set()
        while stack:
            node = stack.pop()
            for nxt in self._waits_for.get(node, ()):  # who node waits on
                if nxt == start:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return False

    # -- public API ---------------------------------------------------------
    def acquire(self, txn_id: int, resource: str, mode: LockMode) -> None:
        with self._cv:
            res = self._resources.setdefault(resource, _ResourceLock())
            # Re-entrant / upgrade handling.
            current = res.holders.get(txn_id)
            if current is mode or (current is LockMode.X and mode is LockMode.S):
                return
            while True:
                upgrading = txn_id in res.holders
                grantable = self._compatible(res, txn_id, mode)
                # An upgrade must wait only for *other* holders.
                if grantable and (not res.waiters or upgrading
                                  or res.waiters[0] == txn_id):
                    res.holders[txn_id] = mode
                    self._waits_for.pop(txn_id, None)
                    if txn_id in res.waiters:
                        res.waiters.remove(txn_id)
                    self._held.setdefault(txn_id, {})[resource] = mode
                    self._cv.notify_all()
                    return

                # Block: record waits-for edges and check for deadlock.
                blockers = self._conflicting_holders(res, txn_id, mode)
                self._waits_for[txn_id] = set(blockers)
                if self._has_cycle(txn_id):
                    self._waits_for.pop(txn_id, None)
                    if txn_id in res.waiters:
                        res.waiters.remove(txn_id)
                    raise DeadlockError(
                        f"deadlock: txn {txn_id} waiting for {sorted(blockers)} "
                        f"on {resource!r}")
                if txn_id not in res.waiters:
                    res.waiters.append(txn_id)
                self._cv.wait()

    def release_all(self, txn_id: int) -> None:
        with self._cv:
            for resource in list(self._held.get(txn_id, {})):
                res = self._resources.get(resource)
                if res is not None:
                    res.holders.pop(txn_id, None)
                    if txn_id in res.waiters:
                        res.waiters.remove(txn_id)
            self._held.pop(txn_id, None)
            self._waits_for.pop(txn_id, None)
            # Clear any stale edges pointing at this txn.
            for waits in self._waits_for.values():
                waits.discard(txn_id)
            self._cv.notify_all()

    def locks_held_by(self, txn_id: int) -> Dict[str, LockMode]:
        with self._cv:
            return dict(self._held.get(txn_id, {}))

    def snapshot(self) -> Dict[str, Dict[int, str]]:
        """Debug view of who holds what (used by the concurrency demo)."""
        with self._cv:
            return {
                r: {t: m.value for t, m in res.holders.items()}
                for r, res in self._resources.items() if res.holders
            }
