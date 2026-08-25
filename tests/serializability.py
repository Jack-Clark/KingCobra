"""An independent serializability oracle.

The generator's version order is total -- values increment by one per write --
so the dependency graph is fully determined and the history is serializable
exactly when that graph is acyclic:

    WR   writer(v)  -> reader(v)
    WW   writer(v)  -> writer(v+1)
    RW   reader(v)  -> writer(v+1)
    CO   txn        -> next txn in the same client log

Checking with and without CO separates plain serializability from strong
session serializability. This shares no code with the verifier, so it is a
genuine second opinion rather than a restatement of the implementation.
"""

from collections import defaultdict

from history_format import parse_log, client_logs


def dependency_edges(history_dir, with_client_order):
    clients = [parse_log(p) for p in client_logs(history_dir)]

    writer = {}                    # (key, version) -> txn id
    readers = defaultdict(list)    # (key, version) -> [txn id]
    for txns in clients:
        for tid, ops in txns:
            for kind, _wid, key, val, _rf in ops:
                if kind == 'W':
                    if (key, val) in writer:
                        raise ValueError('two writes produced key %d version %d' % (key, val))
                    writer[(key, val)] = tid
                else:
                    readers[(key, val)].append(tid)

    edges = set()

    def add(src, dst, kind):
        if src != dst:
            edges.add((src, dst, kind))

    for (key, val), w in writer.items():
        for r in readers[(key, val)]:
            add(w, r, 'WR')
        successor = writer.get((key, val + 1))
        if successor is not None:
            add(w, successor, 'WW')
            for r in readers[(key, val)]:
                add(r, successor, 'RW')

    if with_client_order:
        for txns in clients:
            for (a, _), (b, _) in zip(txns, txns[1:]):
                add(a, b, 'CO')
    return edges


def find_cycle(edges):
    """Returns a list of (src, dst, kind) forming a cycle, or None."""
    adj = defaultdict(list)
    nodes = set()
    for src, dst, kind in edges:
        adj[src].append((dst, kind))
        nodes.add(src)
        nodes.add(dst)

    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(nodes, WHITE)
    on_stack = []

    def visit(u):
        colour[u] = GREY
        for v, kind in adj[u]:
            if colour[v] == GREY:
                on_stack.append((u, v, kind))
                return True
            if colour[v] == WHITE:
                on_stack.append((u, v, kind))
                if visit(v):
                    return True
                on_stack.pop()
        colour[u] = BLACK
        return False

    for node in sorted(nodes):
        if colour[node] == WHITE and visit(node):
            return list(on_stack)
    return None


def is_serializable(history_dir):
    """Ignores client order: plain conflict serializability."""
    return find_cycle(dependency_edges(history_dir, with_client_order=False)) is None


def is_strong_session_serializable(history_dir):
    """Includes client order, so read-your-writes violations show up."""
    return find_cycle(dependency_edges(history_dir, with_client_order=True)) is None
