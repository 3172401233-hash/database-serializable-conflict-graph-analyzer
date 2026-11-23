"""Elementary cycle enumeration over the dependency graph."""

from typing import Dict, List, Tuple


def find_cycles(adjacency):
    # type: (Dict[str, List[str]], ) -> List[Tuple[str, ...]]
    """Enumerate all elementary cycles, each starting at its min node.

    A serializable history has an acyclic dependency graph, so every
    returned cycle is a serializability violation (a "dangerous
    structure"), not merely a single deadlock ring.
    """
    cycles = []  # type: List[Tuple[str, ...]]
    nodes = sorted(adjacency)

    def dfs(start, current, path, visited):
        for nxt in adjacency.get(current, ()):
            if nxt == start:
                cycles.append(tuple(path))
            elif nxt not in visited and nxt >= start:
                visited.add(nxt)
                path.append(nxt)
                dfs(start, nxt, path, visited)
                path.pop()
                visited.remove(nxt)

    for start in nodes:
        dfs(start, start, [start], {start})
    cycles.sort(key=lambda c: (len(c), c))
    return cycles


def cycle_edges(cycle, edges):
    # type: (Tuple[str, ...], List) -> List
    """Return the dependency edges that realize a cycle, in order."""
    by_pair = {}
    for edge in edges:
        by_pair.setdefault((edge.src, edge.dst), []).append(edge)
    result = []
    n = len(cycle)
    for i in range(n):
        src = cycle[i]
        dst = cycle[(i + 1) % n]
        result.extend(by_pair.get((src, dst), []))
    return result
