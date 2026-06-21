"""System catalog: table metadata, heap files, and indexes.

The catalog is the database's metadata layer. For every table it tracks the
schema, the primary key, the list of heap page ids, and any B+Tree indexes.

Metadata (schemas, index definitions, page lists) is persisted as a JSON
sidecar next to the data file. Indexes themselves are **not** persisted — they
are rebuilt by scanning the recovered base table on startup, which keeps the
index layer free of WAL coupling. (Documented as a deliberate trade-off in the
README.) Page lists are persisted here for the clean-restart path and are
additionally reconciled against the write-ahead log during crash recovery.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..index.bplustree import BPlusTree
from ..storage.buffer_pool import BufferPool
from ..storage.heapfile import HeapFile
from .schema import Column, Schema


@dataclass
class IndexInfo:
    name: str
    column: str
    unique: bool
    is_primary: bool = False
    tree: BPlusTree = field(default=None)  # type: ignore[assignment]


@dataclass
class TableInfo:
    name: str
    schema: Schema
    pk_column: Optional[str]
    page_ids: List[int]
    heap: HeapFile
    indexes: Dict[str, IndexInfo] = field(default_factory=dict)

    def index_on(self, column: str) -> Optional[IndexInfo]:
        for idx in self.indexes.values():
            if idx.column == column:
                return idx
        return None

    def primary_index(self) -> Optional[IndexInfo]:
        for idx in self.indexes.values():
            if idx.is_primary:
                return idx
        return None


class Catalog:
    def __init__(self, buffer_pool: BufferPool, catalog_path: str):
        self.bp = buffer_pool
        self.catalog_path = catalog_path
        self.tables: Dict[str, TableInfo] = {}

    # -- DDL ----------------------------------------------------------------
    def create_table(self, name: str, columns: List[Column],
                     pk_column: Optional[str] = None) -> TableInfo:
        if name in self.tables:
            raise ValueError(f"table {name!r} already exists")
        schema = Schema(columns)
        if pk_column is not None and not schema.has_column(pk_column):
            raise ValueError(f"primary key column {pk_column!r} not in schema")
        page_ids: List[int] = []
        heap = HeapFile(name, self.bp, page_ids,
                        register_page=lambda pid, t=name: self._on_page_allocated(t, pid))
        table = TableInfo(name, schema, pk_column, page_ids, heap)
        self.tables[name] = table
        if pk_column is not None:
            idx = IndexInfo(name=f"{name}_pk", column=pk_column, unique=True, is_primary=True)
            idx.tree = BPlusTree(unique=True)
            table.indexes[idx.name] = idx
        self.persist()
        return table

    def create_index(self, table_name: str, column: str,
                     unique: bool = False, name: Optional[str] = None) -> IndexInfo:
        table = self.get_table(table_name)
        if not table.schema.has_column(column):
            raise ValueError(f"no such column {column!r} on {table_name!r}")
        idx_name = name or f"{table_name}_{column}_idx"
        if idx_name in table.indexes:
            raise ValueError(f"index {idx_name!r} already exists")
        idx = IndexInfo(name=idx_name, column=column, unique=unique)
        idx.tree = BPlusTree(unique=unique)
        # Populate from existing rows.
        for rid, rec in table.heap.scan():
            row = table.schema.deserialize(rec)
            idx.tree.insert(row[column], rid)
        table.indexes[idx_name] = idx
        self.persist()
        return idx

    def drop_table(self, name: str) -> None:
        if name not in self.tables:
            raise ValueError(f"no such table {name!r}")
        del self.tables[name]
        self.persist()

    # -- lookups ------------------------------------------------------------
    def get_table(self, name: str) -> TableInfo:
        if name not in self.tables:
            raise ValueError(f"no such table {name!r}")
        return self.tables[name]

    def has_table(self, name: str) -> bool:
        return name in self.tables

    def list_tables(self) -> List[str]:
        return sorted(self.tables)

    # -- index maintenance --------------------------------------------------
    def rebuild_indexes(self, table_name: str) -> None:
        """Rebuild every index on a table from its (recovered) heap contents."""
        table = self.get_table(table_name)
        for idx in table.indexes.values():
            idx.tree = BPlusTree(unique=idx.unique)
        for rid, rec in table.heap.scan():
            row = table.schema.deserialize(rec)
            for idx in table.indexes.values():
                idx.tree.insert(row[idx.column], rid)

    def rebuild_all_indexes(self) -> None:
        for name in self.tables:
            self.rebuild_indexes(name)

    def adopt_pages(self, table_name: str, page_ids) -> None:
        """Merge page ids discovered during recovery into a table's heap."""
        if table_name not in self.tables:
            return
        table = self.tables[table_name]
        known = set(table.page_ids)
        for pid in sorted(page_ids):
            if pid not in known:
                table.page_ids.append(pid)
                known.add(pid)

    def _on_page_allocated(self, table_name: str, page_id: int) -> None:
        # Page lists are made durable as soon as space is allocated.
        self.persist()

    # -- persistence --------------------------------------------------------
    def to_doc(self) -> dict:
        """Serialise all metadata to a plain dict (also shipped to replicas)."""
        doc = {"tables": {}}
        for name, t in self.tables.items():
            doc["tables"][name] = {
                "schema": t.schema.to_dict(),
                "pk_column": t.pk_column,
                "page_ids": list(t.page_ids),
                "indexes": [
                    {"name": i.name, "column": i.column,
                     "unique": i.unique, "is_primary": i.is_primary}
                    for i in t.indexes.values()
                ],
            }
        return doc

    def persist(self) -> None:
        doc = self.to_doc()
        tmp = self.catalog_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.catalog_path)

    def load(self) -> None:
        """Load metadata from disk and rebuild in-memory heap/index objects."""
        if not os.path.exists(self.catalog_path):
            return
        with open(self.catalog_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.load_from_doc(doc)

    def load_from_doc(self, doc: dict) -> None:
        """Build in-memory tables/heaps/index stubs from a metadata dict.

        Used both by ``load`` (from the JSON sidecar) and by a replica when it
        receives the primary's catalog snapshot.
        """
        self.tables.clear()
        for name, td in doc.get("tables", {}).items():
            schema = Schema.from_dict(td["schema"])
            page_ids = list(td.get("page_ids", []))
            heap = HeapFile(name, self.bp, page_ids,
                            register_page=lambda pid, t=name: self._on_page_allocated(t, pid))
            table = TableInfo(name, schema, td.get("pk_column"), page_ids, heap)
            for idef in td.get("indexes", []):
                idx = IndexInfo(name=idef["name"], column=idef["column"],
                                unique=idef["unique"], is_primary=idef.get("is_primary", False))
                idx.tree = BPlusTree(unique=idx.unique)
                table.indexes[idx.name] = idx
            self.tables[name] = table
        # Indexes are rebuilt by the engine after recovery has restored heaps.
