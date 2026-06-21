"""Crash recovery — an ARIES-style three-pass algorithm.

On startup the engine replays the write-ahead log to restore the database to a
transactionally consistent state. Recovery runs three passes:

1. **Analysis** — scan the log (from the last checkpoint) to determine which
   transactions were *losers* (BEGIN seen but no COMMIT/ABORT). Committed
   transactions are *winners*. Also collect, per table, the set of page ids the
   log touched, so the catalog's heap page lists can be reconciled.

2. **Redo** — replay every logged change forward, re-applying the *after* image
   to its page, but only when the page has not already seen it
   (``page.lsn < record.lsn``). This brings the on-disk state up to the moment
   of the crash, including changes from loser transactions ("repeating
   history", as ARIES does).

3. **Undo** — roll back the loser transactions by walking each one's prev-LSN
   chain backwards and applying the *before* image, writing a compensation log
   record (CLR) for each undone change.

After recovery the engine rebuilds indexes from the restored heaps. The net
effect: every committed transaction is preserved and every uncommitted one
vanishes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Set

from ..storage.buffer_pool import BufferPool
from . import page_ops
from .log_manager import LogManager
from .log_record import LogRecord, LogType


@dataclass
class RecoveryReport:
    winners: Set[int] = field(default_factory=set)
    losers: Set[int] = field(default_factory=set)
    redo_count: int = 0
    undo_count: int = 0
    table_pages: Dict[str, Set[int]] = field(default_factory=lambda: defaultdict(set))

    def summary(self) -> str:
        return (f"recovery: {len(self.winners)} committed, {len(self.losers)} rolled "
                f"back, {self.redo_count} redos, {self.undo_count} undos")


class RecoveryManager:
    def __init__(self, log_manager: LogManager, buffer_pool: BufferPool):
        self.log = log_manager
        self.bp = buffer_pool

    def recover(self) -> RecoveryReport:
        records = self.log.records()
        report = RecoveryReport()
        if not records:
            return report

        start_lsn = self.log.last_checkpoint_lsn()

        # --- Pass 1: analysis ---------------------------------------------
        txn_status: Dict[int, str] = {}     # txn_id -> 'active' | 'done'
        for rec in records:
            if rec.table and rec.page_id >= 0:
                report.table_pages[rec.table].add(rec.page_id)
            if rec.type is LogType.BEGIN:
                txn_status[rec.txn_id] = "active"
            elif rec.type in (LogType.COMMIT, LogType.ABORT):
                txn_status[rec.txn_id] = "done"
                if rec.type is LogType.COMMIT:
                    report.winners.add(rec.txn_id)
        report.losers = {t for t, s in txn_status.items() if s == "active"}

        # --- Pass 2: redo (repeat history) --------------------------------
        # Re-apply every data change forward — winners and losers alike — so
        # the on-disk state matches the instant of the crash. The page LSN
        # guards against re-applying a change a page already reflects.
        for rec in records:
            if rec.lsn < start_lsn:
                continue
            if rec.type not in (LogType.INSERT, LogType.DELETE, LogType.UPDATE):
                continue
            if rec.page_id < 0 or rec.page_id >= self.bp.disk.num_pages:
                continue
            page = self.bp.fetch_page(rec.page_id)
            try:
                if page.lsn < rec.lsn:
                    page_ops.redo(rec, page)
                    page.lsn = rec.lsn
                    report.redo_count += 1
                    self.bp.unpin_page(rec.page_id, True)
                else:
                    self.bp.unpin_page(rec.page_id, False)
            except Exception:
                self.bp.unpin_page(rec.page_id, False)
                raise

        # --- Pass 3: undo losers ------------------------------------------
        # Undo most-recent change first across all losers. Each undo targets a
        # specific (page, slot) with a specific image, so it is idempotent —
        # re-running it after a crash mid-undo is harmless.
        to_undo: List[LogRecord] = sorted(
            (r for r in records
             if r.txn_id in report.losers
             and r.type in (LogType.INSERT, LogType.DELETE, LogType.UPDATE)),
            key=lambda r: r.lsn, reverse=True)
        for rec in to_undo:
            page = self.bp.fetch_page(rec.page_id)
            try:
                page_ops.undo(rec, page)
                clr = LogRecord(type=LogType.CLR, txn_id=rec.txn_id,
                                table=rec.table, page_id=rec.page_id,
                                slot_no=rec.slot_no, undo_next_lsn=rec.prev_lsn)
                clr_lsn = self.log.append(clr)
                page.lsn = clr_lsn
                report.undo_count += 1
            finally:
                self.bp.unpin_page(rec.page_id, True)
        # Mark each loser aborted in the log.
        for txn_id in sorted(report.losers):
            self.log.append(LogRecord(type=LogType.ABORT, txn_id=txn_id))

        self.bp.flush_all()
        self.log.flush()
        return report
