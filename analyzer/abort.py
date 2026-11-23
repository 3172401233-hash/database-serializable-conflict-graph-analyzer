"""Abort-set selection: minimum feedback vertex sets over the cycles.

Breaking every elementary cycle requires a hitting set (a.k.a. feedback
vertex set) over the cycle collection. We enumerate minimum-size sets
exactly (the graphs here are small) and rank them by abort cost so that
long transactions are spared when a cheaper alternative exists.
"""

from typing import Dict, FrozenSet, List, Tuple

from .cycles import find_cycles

# A transaction whose duration reaches this threshold is "long".
LONG_TXN_THRESHOLD = 50
# Extra risk weight for aborting a long transaction.
LONG_TXN_PENALTY = 2


def abort_cost(txn):
    """Cost of aborting one transaction: base 1 plus its duration."""
    return 1 + txn.duration


def _min_hitting_sets(cycles, limit=64):
    # type: (List[Tuple[str, ...]], int) -> List[FrozenSet[str]]
    """Enumerate all minimum-size hitting sets of the cycle collection."""
    best = [None]  # type: List[object]
    results = []  # type: List[FrozenSet[str]]

    def backtrack(uncovered, chosen):
        if best[0] is not None and len(chosen) > best[0]:
            return
        if len(results) >= limit:
            return
        if not uncovered:
            chosen_fs = frozenset(chosen)
            if best[0] is None or len(chosen) < best[0]:
                best[0] = len(chosen)
                del results[:]
            if chosen_fs not in results:
                results.append(chosen_fs)
            return
        cycle = min(uncovered, key=len)
        for node in cycle:
            backtrack([c for c in uncovered if node not in c],
                      chosen | {node})

    backtrack(list(cycles), frozenset())
    return results


class AbortPlan(object):
    """One candidate abort set with its risk assessment."""

    def __init__(self, abort_set, transactions, cycles_broken,
                 remaining_cycles):
        # type: (FrozenSet[str], Dict[str, object], int, List[Tuple[str, ...]]) -> None
        self.abort_set = tuple(sorted(abort_set))
        self.abort_count = len(self.abort_set)
        self.total_cost = sum(abort_cost(transactions[t])
                              for t in self.abort_set)
        self.long_transactions = tuple(
            t for t in self.abort_set
            if transactions[t].duration >= LONG_TXN_THRESHOLD)
        self.cycles_broken = cycles_broken
        self.remaining_cycles = list(remaining_cycles)
        self.risk_score = (self.total_cost +
                           LONG_TXN_PENALTY * len(self.long_transactions))
        if not self.abort_set:
            self.risk_level = "none"
        elif self.risk_score <= 2:
            self.risk_level = "low"
        elif self.risk_score <= 5:
            self.risk_level = "medium"
        else:
            self.risk_level = "high"

    def sort_key(self):
        # Deterministic tie break: fewer aborts, cheaper, then ids.
        return (self.abort_count, self.total_cost, self.abort_set)

    def __repr__(self):
        return "AbortPlan(abort=%s, cost=%d, risk=%s)" % (
            list(self.abort_set), self.total_cost, self.risk_level)


def compute_abort_plans(cycles, adjacency, transactions, limit=3):
    # type: (List[Tuple[str, ...]], Dict[str, List[str]], Dict[str, object], int) -> List[AbortPlan]
    """Rank minimum abort sets; recompute the residual graph per plan.

    Returns up to ``limit`` plans ordered by (abort count, cost, ids).
    """
    if not cycles:
        return [AbortPlan(frozenset(), transactions, 0, [])]

    hitting_sets = _min_hitting_sets(cycles)
    plans = []
    for hitting in hitting_sets:
        residual_adj = {
            node: [dst for dst in dsts if dst not in hitting]
            for node, dsts in adjacency.items()
            if node not in hitting
        }
        remaining = find_cycles(residual_adj)
        broken = sum(1 for c in cycles if set(c) & hitting)
        plans.append(AbortPlan(hitting, transactions, broken, remaining))

    plans.sort(key=lambda p: p.sort_key())
    return plans[:limit]
