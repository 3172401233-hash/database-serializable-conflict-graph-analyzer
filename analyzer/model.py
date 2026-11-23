"""Data model for the serializable conflict graph analyzer.

This module only describes transaction metadata. The analyzer never
executes any database transaction; it performs static analysis over
the read/write sets, versions, commit order and predicate reads that
callers provide.
"""

from typing import Dict, Iterable, List, Optional, Tuple


class Predicate(object):
    """A predicate read (e.g. a range scan or a key filter).

    A predicate matches a key either through an explicit key set or
    through an inclusive ``key_range`` of comparable keys.
    """

    def __init__(self, name, keys=None, key_range=None):
        # type: (str, Optional[Iterable], Optional[Tuple]) -> None
        if keys is None and key_range is None:
            raise ValueError("predicate %r needs keys or key_range" % name)
        self.name = name
        self.keys = set(keys) if keys is not None else None
        self.key_range = key_range

    def matches(self, key):
        if self.keys is not None and key in self.keys:
            return True
        if self.key_range is not None:
            lo, hi = self.key_range
            try:
                return lo <= key <= hi
            except TypeError:
                return False
        return False

    def __repr__(self):
        return "Predicate(%r)" % (self.name,)


class Transaction(object):
    """Static description of one transaction's footprint.

    Attributes:
        txn_id: unique identifier (must be sortable, e.g. str).
        reads: mapping key -> version read (None if version unknown).
        writes: mapping key -> version written.
        predicate_reads: list of Predicate objects observed by reads.
        commit_order: position in the committed order (int).
        start_ts / commit_ts: optional logical timestamps; their delta
            is the transaction duration used to flag long transactions.
        aborted: True if the transaction already aborted; such
            transactions are excluded from the conflict graph.
    """

    def __init__(self, txn_id, reads=None, writes=None, predicate_reads=None,
                 commit_order=0, start_ts=None, commit_ts=None, aborted=False):
        # type: (str, Optional[Dict], Optional[Dict], Optional[List[Predicate]], int, Optional[int], Optional[int], bool) -> None
        self.txn_id = txn_id
        self.reads = dict(reads or {})
        self.writes = dict(writes or {})
        self.predicate_reads = list(predicate_reads or [])
        self.commit_order = commit_order
        self.start_ts = start_ts
        self.commit_ts = commit_ts
        self.aborted = aborted

    @property
    def duration(self):
        # type: () -> int
        if self.start_ts is None or self.commit_ts is None:
            return 0
        return max(0, self.commit_ts - self.start_ts)

    def __repr__(self):
        return "Transaction(%r)" % (self.txn_id,)


# Dependency edge kinds.
EDGE_WR = "wr"  # write -> read: src wrote a version dst read
EDGE_RW = "rw"  # read -> write anti-dependency (incl. phantom)
EDGE_WW = "ww"  # write -> write: src overwritten by dst


class DependencyEdge(object):
    """A directed dependency edge src -> dst."""

    def __init__(self, src, dst, kind, key, reason=""):
        # type: (str, str, str, object, str) -> None
        self.src = src
        self.dst = dst
        self.kind = kind
        self.key = key
        self.reason = reason

    def identity(self):
        # type: () -> Tuple
        return (self.src, self.dst, self.kind, self.key)

    def __repr__(self):
        return "DependencyEdge(%s -[%s:%s]-> %s)" % (
            self.src, self.kind, self.key, self.dst)
