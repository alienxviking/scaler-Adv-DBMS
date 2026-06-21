"""Tests for Track D: primary-replica replication and failover."""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from minidb.engine import Database
from minidb.replication.primary import Primary
from minidb.replication.replica import Replica


def _pair(tmp_path):
    primary = Database(str(tmp_path / "primary"), pool_size=64)
    replica_db = Database(str(tmp_path / "replica"), pool_size=64)
    return primary, replica_db


def test_inprocess_replication_read_consistency(tmp_path):
    primary, replica_db = _pair(tmp_path)
    c = primary.connect()
    c.execute("CREATE TABLE t (id INT PRIMARY KEY, v TEXT)")
    c.execute("INSERT INTO t VALUES (1,'a'),(2,'b'),(3,'c')")

    prim = Primary(primary)
    rep = Replica(replica_db)
    lsn = prim.replicate_to(rep, from_lsn=0)
    assert lsn > 0

    # Replica reads reflect the primary's committed data.
    rows = sorted(r[0] for r in rep.query("SELECT id FROM t").rows)
    assert rows == [1, 2, 3]
    assert rep.query("SELECT v FROM t WHERE id = 2").rows == [["b"]]

    # Incremental change propagates.
    c.execute("INSERT INTO t VALUES (4,'d')")
    c.execute("DELETE FROM t WHERE id = 1")
    prim.replicate_to(rep, from_lsn=lsn)
    rows = sorted(r[0] for r in rep.query("SELECT id FROM t").rows)
    assert rows == [2, 3, 4]
    primary.close(); replica_db.close()


def test_replica_promotion_accepts_writes(tmp_path):
    primary, replica_db = _pair(tmp_path)
    c = primary.connect()
    c.execute("CREATE TABLE t (id INT PRIMARY KEY, v TEXT)")
    c.execute("INSERT INTO t VALUES (1,'a')")
    prim, rep = Primary(primary), Replica(replica_db)
    prim.replicate_to(rep, 0)

    rep.promote()                       # primary "failed"
    rc = rep.db.connect()
    rc.execute("INSERT INTO t VALUES (2,'written-on-replica')")
    rows = sorted(r[0] for r in rc.execute("SELECT id FROM t").rows)
    assert rows == [1, 2]
    primary.close(); replica_db.close()


def test_live_socket_streaming_and_failover(tmp_path):
    primary, replica_db = _pair(tmp_path)
    c = primary.connect()
    c.execute("CREATE TABLE t (id INT PRIMARY KEY, v TEXT)")
    c.execute("INSERT INTO t VALUES (1,'a'),(2,'b')")

    prim = Primary(primary)
    port = prim.serve("127.0.0.1", 0)
    rep = Replica(replica_db)
    rep.start_following("127.0.0.1", port)

    # Wait for initial catch-up.
    deadline = time.time() + 5
    while time.time() < deadline and rep.applied_lsn < primary.log.current_lsn:
        time.sleep(0.05)
    assert sorted(r[0] for r in rep.query("SELECT id FROM t").rows) == [1, 2]

    # New writes stream live.
    c.execute("INSERT INTO t VALUES (3,'c')")
    deadline = time.time() + 5
    while time.time() < deadline and rep.applied_lsn < primary.log.current_lsn:
        time.sleep(0.05)
    assert sorted(r[0] for r in rep.query("SELECT id FROM t").rows) == [1, 2, 3]

    # Failover: stop the primary, promote the replica, write locally.
    prim.stop()
    rep.promote()
    rc = rep.db.connect()
    rc.execute("INSERT INTO t VALUES (4,'after-failover')")
    assert sorted(r[0] for r in rc.execute("SELECT id FROM t").rows) == [1, 2, 3, 4]

    rep.stop()
    primary.close(); replica_db.close()
