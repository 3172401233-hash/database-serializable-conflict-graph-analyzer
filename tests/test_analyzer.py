import unittest

from analyzer import (EDGE_RW, EDGE_WR, EDGE_WW, Predicate, Transaction,
                      analyze)


def write_skew_transactions():
    """Classic write skew: T1 and T2 each read A,B then write one of them."""
    return [
        Transaction("T0", writes={"A": 0, "B": 0}, commit_order=0),
        Transaction("T1", reads={"A": 0, "B": 0}, writes={"A": 1},
                    commit_order=1),
        Transaction("T2", reads={"A": 0, "B": 0}, writes={"B": 1},
                    commit_order=2),
    ]


class WriteSkewTest(unittest.TestCase):
    def test_write_skew_cycle(self):
        report = analyze(write_skew_transactions())
        self.assertFalse(report.is_serializable)
        self.assertIn(("T1", "T2"), report.cycles)
        rw_pairs = {(e.src, e.dst) for e in report.edges if e.kind == EDGE_RW}
        self.assertIn(("T1", "T2"), rw_pairs)
        self.assertIn(("T2", "T1"), rw_pairs)

    def test_single_abort_breaks_skew(self):
        report = analyze(write_skew_transactions())
        best = report.best_plan()
        self.assertEqual(best.abort_count, 1)
        self.assertEqual(best.remaining_cycles, [])
        residual = report.recompute(best.abort_set)
        self.assertTrue(residual.is_serializable)


class PhantomReadTest(unittest.TestCase):
    def test_predicate_phantom(self):
        txns = [
            Transaction("T1", reads={"x": 1},
                        predicate_reads=[Predicate("range", key_range=(1, 10))],
                        commit_order=1),
            Transaction("T2", writes={"x": 1, 5: 1}, commit_order=2),
        ]
        report = analyze(txns)
        kinds = {(e.src, e.dst, e.kind) for e in report.edges}
        # Phantom: T2 inserts key 5 matching T1's predicate after T1 read.
        self.assertIn(("T1", "T2", EDGE_RW), kinds)
        # T1 read version 1 of x written by T2.
        self.assertIn(("T2", "T1", EDGE_WR), kinds)
        self.assertIn(("T1", "T2"), report.cycles)

    def test_phantom_edge_reason_mentions_predicate(self):
        txns = [
            Transaction("T1",
                        predicate_reads=[Predicate("p", key_range=(0, 9))],
                        commit_order=1),
            Transaction("T2", writes={3: 1}, commit_order=2),
        ]
        report = analyze(txns)
        phantom = [e for e in report.edges
                   if e.kind == EDGE_RW and e.src == "T1"]
        self.assertEqual(len(phantom), 1)
        self.assertIn("phantom", phantom[0].reason)
        # No cycle here: a lone phantom edge is not a violation by itself.
        self.assertTrue(report.is_serializable)


class CrossDependencyTest(unittest.TestCase):
    def test_three_node_mixed_cycle(self):
        txns = [
            Transaction("T0", writes={"b": 0}, commit_order=0),
            Transaction("T1", reads={"d": 1}, writes={"a": 1},
                        commit_order=1),
            Transaction("T2", reads={"a": 1, "b": 0}, commit_order=2),
            Transaction("T3", writes={"b": 1, "d": 1}, commit_order=3),
        ]
        report = analyze(txns)
        self.assertIn(("T1", "T2", "T3"), report.cycles)
        cycle_kinds = {e.kind for e in report.cycle_edge_details(
            ("T1", "T2", "T3"))}
        self.assertEqual(cycle_kinds, {EDGE_WR, EDGE_RW})

    def test_ww_edge_and_combined_cycle(self):
        txns = [
            Transaction("T1", reads={"y": 1}, writes={"x": 1},
                        commit_order=1),
            Transaction("T2", reads={"x": 1}, writes={"x": 2, "y": 1},
                        commit_order=2),
        ]
        report = analyze(txns)
        kinds = {(e.src, e.dst, e.kind) for e in report.edges}
        self.assertIn(("T1", "T2", EDGE_WW), kinds)   # x overwritten
        self.assertIn(("T1", "T2", EDGE_WR), kinds)   # T2 read x v1
        self.assertIn(("T2", "T1", EDGE_WR), kinds)   # T1 read y v1
        self.assertIn(("T1", "T2"), report.cycles)


class VersionedReadTest(unittest.TestCase):
    def test_old_version_read_creates_rw_antidependency(self):
        txns = [
            Transaction("T0", writes={"k": 0}, commit_order=0),
            Transaction("T1", writes={"k": 1}, commit_order=1),
            Transaction("T2", reads={"k": 0}, commit_order=2),
        ]
        report = analyze(txns)
        kinds = {(e.src, e.dst, e.kind) for e in report.edges}
        self.assertIn(("T0", "T2", EDGE_WR), kinds)
        self.assertIn(("T2", "T1", EDGE_RW), kinds)
        self.assertIn(("T0", "T1", EDGE_WW), kinds)
        self.assertTrue(report.is_serializable)


class AbortedTransactionTest(unittest.TestCase):
    def test_aborted_transactions_are_excluded(self):
        txns = write_skew_transactions()
        txns.append(Transaction("T9", reads={"A": 1, "B": 1},
                                writes={"A": 9, "B": 9},
                                commit_order=9, aborted=True))
        report = analyze(txns)
        self.assertEqual(report.excluded_aborted, ["T9"])
        nodes = {e.src for e in report.edges} | {e.dst for e in report.edges}
        self.assertNotIn("T9", nodes)
        self.assertNotIn("T9", {t.txn_id for t in report.committed})


class TieBreakTest(unittest.TestCase):
    def test_equal_cost_plans_break_tie_by_ids(self):
        report = analyze(write_skew_transactions(), plan_limit=5)
        self.assertGreaterEqual(len(report.abort_plans), 2)
        first, second = report.abort_plans[0], report.abort_plans[1]
        self.assertEqual(first.abort_set, ("T1",))
        self.assertEqual(second.abort_set, ("T2",))
        self.assertEqual(first.total_cost, second.total_cost)

    def test_long_transaction_is_spared(self):
        txns = [
            Transaction("T0", writes={"A": 0, "B": 0}, commit_order=0),
            Transaction("Tshort", reads={"A": 0, "B": 0}, writes={"A": 1},
                        commit_order=1, start_ts=0, commit_ts=2),
            Transaction("Tlong", reads={"A": 0, "B": 0}, writes={"B": 1},
                        commit_order=2, start_ts=0, commit_ts=500),
        ]
        report = analyze(txns, plan_limit=5)
        best = report.best_plan()
        self.assertEqual(best.abort_set, ("Tshort",))
        self.assertEqual(best.long_transactions, ())
        long_plan = [p for p in report.abort_plans
                     if p.abort_set == ("Tlong",)][0]
        self.assertEqual(long_plan.long_transactions, ("Tlong",))
        self.assertGreater(long_plan.risk_score, best.risk_score)


class MultipleAnomaliesTest(unittest.TestCase):
    def test_two_disjoint_cycles_one_plan(self):
        txns = [
            Transaction("T0", writes={"A": 0, "B": 0, "C": 0, "D": 0},
                        commit_order=0),
            Transaction("T1", reads={"A": 0, "B": 0}, writes={"A": 1},
                        commit_order=1),
            Transaction("T2", reads={"A": 0, "B": 0}, writes={"B": 1},
                        commit_order=2),
            Transaction("T3", reads={"C": 0, "D": 0}, writes={"C": 1},
                        commit_order=3),
            Transaction("T4", reads={"C": 0, "D": 0}, writes={"D": 1},
                        commit_order=4),
        ]
        report = analyze(txns)
        self.assertEqual(len(report.cycles), 2)
        best = report.best_plan()
        self.assertEqual(best.abort_set, ("T1", "T3"))
        self.assertEqual(best.cycles_broken, 2)
        self.assertEqual(best.remaining_cycles, [])
        residual = report.recompute(best.abort_set)
        self.assertTrue(residual.is_serializable)

    def test_recompute_with_partial_abort_keeps_cycle(self):
        txns = write_skew_transactions()
        report = analyze(txns)
        # Aborting an unrelated transaction changes nothing.
        txns.append(Transaction("T5", writes={"Z": 1}, commit_order=5))
        report = analyze(txns)
        residual = report.recompute({"T5"})
        self.assertFalse(residual.is_serializable)
        self.assertIn(("T1", "T2"), residual.cycles)


class SerializableTest(unittest.TestCase):
    def test_acyclic_history_has_empty_abort_plan(self):
        txns = [
            Transaction("T1", writes={"a": 1}, commit_order=1),
            Transaction("T2", reads={"a": 1}, writes={"b": 1},
                        commit_order=2),
            Transaction("T3", reads={"b": 1}, commit_order=3),
        ]
        report = analyze(txns)
        self.assertTrue(report.is_serializable)
        best = report.best_plan()
        self.assertEqual(best.abort_set, ())
        self.assertEqual(best.risk_level, "none")


if __name__ == "__main__":
    unittest.main()
