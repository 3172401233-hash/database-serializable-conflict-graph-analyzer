"""Top-level analysis API: build graph, find cycles, rank abort plans."""

from typing import Dict, Iterable, List, Tuple

from .abort import AbortPlan, compute_abort_plans
from .cycles import cycle_edges, find_cycles
from .graph import build_dependency_graph
from .model import DependencyEdge, Transaction


class AnalysisReport(object):
    """Result of one analysis pass over a set of transactions."""

    def __init__(self, transactions, committed, edges, adjacency, cycles,
                 abort_plans):
        # type: (List[Transaction], List[Transaction], List[DependencyEdge], Dict, List[Tuple[str, ...]], List[AbortPlan]) -> None
        self.transactions = list(transactions)
        self.committed = list(committed)
        self.excluded_aborted = [t.txn_id for t in transactions if t.aborted]
        self.edges = list(edges)
        self.adjacency = adjacency
        self.cycles = list(cycles)
        self.abort_plans = list(abort_plans)

    @property
    def is_serializable(self):
        # type: () -> bool
        return not self.cycles

    def best_plan(self):
        # type: () -> AbortPlan
        return self.abort_plans[0]

    def recompute(self, abort_set):
        # type: (Iterable[str]) -> AnalysisReport
        """Re-run the analysis with the given transactions removed."""
        abort_set = set(abort_set)
        remaining = [t for t in self.transactions
                     if t.txn_id not in abort_set]
        return analyze(remaining)

    def cycle_edge_details(self, cycle):
        # type: (Tuple[str, ...]) -> List[DependencyEdge]
        return cycle_edges(cycle, self.edges)

    def format(self):
        # type: () -> str
        lines = []
        lines.append("committed transactions: %s"
                     % [t.txn_id for t in self.committed])
        if self.excluded_aborted:
            lines.append("excluded (already aborted): %s"
                         % self.excluded_aborted)
        lines.append("dependency edges: %d" % len(self.edges))
        for edge in self.edges:
            lines.append("  %s -[%s:%s]-> %s  (%s)"
                         % (edge.src, edge.kind, edge.key,
                            edge.dst, edge.reason))
        if not self.cycles:
            lines.append("no serializability violation: graph is acyclic")
        else:
            lines.append("violation cycles: %d" % len(self.cycles))
            for cycle in self.cycles:
                lines.append("  %s" % (" -> ".join(cycle + (cycle[0],))))
        lines.append("abort plans:")
        for plan in self.abort_plans:
            lines.append(
                "  abort=%s cost=%d broken=%d remaining=%d risk=%s"
                % (list(plan.abort_set), plan.total_cost,
                   plan.cycles_broken, len(plan.remaining_cycles),
                   plan.risk_level))
        return "\n".join(lines)


def analyze(transactions, plan_limit=3):
    # type: (List[Transaction], int) -> AnalysisReport
    """Analyze transactions and return an AnalysisReport.

    Pure static analysis: no database transaction is executed here.
    """
    transactions = list(transactions)
    committed, edges, adjacency = build_dependency_graph(transactions)
    cycles = find_cycles(adjacency)
    by_id = {t.txn_id: t for t in committed}
    plans = compute_abort_plans(cycles, adjacency, by_id, limit=plan_limit)
    return AnalysisReport(transactions, committed, edges, adjacency,
                          cycles, plans)
