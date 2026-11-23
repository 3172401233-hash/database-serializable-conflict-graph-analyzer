"""Build the rw / wr / ww dependency graph from transaction metadata."""

from typing import Dict, List, Tuple

from .model import (EDGE_RW, EDGE_WR, EDGE_WW, DependencyEdge, Transaction)


def _ordered_committed(transactions):
    # type: (List[Transaction]) -> List[Transaction]
    committed = [t for t in transactions if not t.aborted]
    return sorted(committed, key=lambda t: (t.commit_order, t.txn_id))


def build_dependency_graph(transactions):
    # type: (List[Transaction]) -> Tuple[List[Transaction], List[DependencyEdge], Dict]
    """Return (committed_txns, edges, adjacency).

    Aborted transactions are excluded: they leave no committed writes,
    so they cannot participate in a serialization anomaly.
    """
    ordered = _ordered_committed(transactions)
    edges = {}  # type: Dict[Tuple, DependencyEdge]

    def add(src, dst, kind, key, reason):
        if src == dst:
            return
        edge = DependencyEdge(src, dst, kind, key, reason)
        edges.setdefault(edge.identity(), edge)

    # Index committed writers per key in commit order.
    writers = {}  # type: Dict[object, List[Tuple[Transaction, object]]]
    for txn in ordered:
        for key, version in txn.writes.items():
            writers.setdefault(key, []).append((txn, version))

    # ww: every earlier writer is ordered before every later writer.
    for key, key_writers in writers.items():
        for i in range(len(key_writers)):
            for j in range(i + 1, len(key_writers)):
                add(key_writers[i][0].txn_id, key_writers[j][0].txn_id,
                    EDGE_WW, key, "overwrite")

    # Keyed reads: wr from the version's writer, rw to later writers.
    for txn in ordered:
        for key, version in txn.reads.items():
            key_writers = writers.get(key, [])
            source = None
            if version is not None:
                for writer, w_version in key_writers:
                    if w_version == version and writer is not txn:
                        source = writer
            elif key_writers:
                prior = [w for w, _ in key_writers
                         if w.commit_order < txn.commit_order and w is not txn]
                if prior:
                    source = prior[-1]
            if source is not None:
                add(source.txn_id, txn.txn_id, EDGE_WR, key,
                    "read version %r" % (version,))
            for writer, w_version in key_writers:
                if writer is txn or writer is source:
                    continue
                if w_version == version:
                    continue
                if source is None or writer.commit_order > source.commit_order:
                    add(txn.txn_id, writer.txn_id, EDGE_RW, key,
                        "overwritten after read")

    # Predicate reads: wr for matched committed writes, rw for phantoms.
    for txn in ordered:
        for pred in txn.predicate_reads:
            for writer in ordered:
                if writer is txn:
                    continue
                for key in writer.writes:
                    if not pred.matches(key):
                        continue
                    if writer.commit_order < txn.commit_order:
                        add(writer.txn_id, txn.txn_id, EDGE_WR, key,
                            "predicate %s matched" % pred.name)
                    else:
                        add(txn.txn_id, writer.txn_id, EDGE_RW, key,
                            "phantom via predicate %s" % pred.name)

    adjacency = {}  # type: Dict[str, List[str]]
    for edge in edges.values():
        adjacency.setdefault(edge.src, [])
        if edge.dst not in adjacency[edge.src]:
            adjacency[edge.src].append(edge.dst)
    for node in adjacency:
        adjacency[node].sort()

    edge_list = sorted(edges.values(),
                       key=lambda e: (e.src, e.dst, e.kind, repr(e.key)))
    return ordered, edge_list, adjacency
