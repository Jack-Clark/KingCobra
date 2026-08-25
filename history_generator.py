#!/usr/bin/env python3
"""Generate synthetic transaction histories and version orders for King Cobra.

A history is written as one binary log per client, in the format the Cobra
verifier's log parser expects (see AbstractVerifier.loadLogs). Alongside it,
a version order file records, for each key, the sequence of values that key
took -- the extra information King Cobra consumes when VERSION_ORDER_ON is set.

Values are integers that increase by one per write, so a value doubles as a
version number and is unique per key. King Cobra relies on that uniqueness to
map a version back to the write that produced it.

See the README for the on-disk formats and for worked examples.
"""

import argparse
import os
import random
import sys

INT_BYTES = 8
BYTE_ORDER = 'big'


def _long(n):
    return n.to_bytes(INT_BYTES, byteorder=BYTE_ORDER)


class Op:
    """A single read or write. `wid` names the write that produced the value:
    for a write, its own id; for a read, the id of the write it read from."""

    def __init__(self, wid, is_read, key, val, prev_tx_id=-1):
        self.wid = wid
        self.is_read = is_read
        self.key = key
        self.val = val
        self.prev_tx_id = prev_tx_id  # transaction this read read from

    def __bytes__(self):
        if self.is_read:
            return b'R' + _long(self.prev_tx_id) + _long(self.wid) + _long(self.key) + _long(self.val)
        return b'W' + _long(self.wid) + _long(self.key) + _long(self.val)


class Transaction:
    def __init__(self, tid):
        self.tid = tid
        self.ops = []
        self.write_keys = set()
        self.read_keys = set()

    def __bytes__(self):
        body = b''.join(bytes(op) for op in self.ops)
        return b'S' + _long(self.tid) + body + b'C' + _long(self.tid)

    def add_op(self, op):
        if op.is_read:
            self.read_keys.add(op.key)
        else:
            self.write_keys.add(op.key)
        self.ops.append(op)


class IncrementHistoryGenerator:
    """Generates histories over `max_keys` keys, each starting at value 0.

    Tracks, per key, the latest value and a value -> write id map, which is what
    lets a generated version order be resolved back to concrete writes.
    """

    def __init__(self, max_keys, read_ratio, write_ratio):
        self.next_wid = 1
        self.next_tid = 1
        self.max_keys = max_keys
        self.read_ratio = read_ratio
        self.write_ratio = write_ratio
        self.db = {}          # key -> (latest value, {value: wid})
        self.wid_to_txid = {}

    def get_next_tid(self):
        tid = self.next_tid
        self.next_tid += 1
        return tid

    def _next_wid(self):
        wid = self.next_wid
        self.next_wid += 1
        return wid

    def _pick_unused_key(self, tx):
        """Pick a key this transaction has not touched yet. Callers must ensure
        the transaction cannot exhaust the key space; see check_feasible."""
        used = tx.read_keys | tx.write_keys
        return random.choice([k for k in range(self.max_keys) if k not in used])

    def _bump(self, key, wid, tid):
        """Record that `wid` (in `tid`) wrote the next version of `key`."""
        val, vals = self.db[key]
        vals[val + 1] = wid
        self.db[key] = (val + 1, vals)
        self.wid_to_txid[wid] = tid
        return val + 1

    def insert_keys(self):
        """The initial transaction, writing value 0 to every key."""
        init_tx = Transaction(self.get_next_tid())
        for key in range(self.max_keys):
            wid = self._next_wid()
            self.db[key] = (0, {0: wid})
            init_tx.add_op(Op(wid, False, key, 0))
            self.wid_to_txid[wid] = init_tx.tid
        return init_tx

    def generate_read_op(self, tx):
        key = self._pick_unused_key(tx)
        val, vals = self.db[key]
        wid = vals[val]
        return Op(wid, True, key, val, prev_tx_id=self.wid_to_txid[wid])

    def generate_write_op(self, tx):
        key = self._pick_unused_key(tx)
        wid = self._next_wid()
        return Op(wid, False, key, self._bump(key, wid, tx.tid))

    def generate_rmw_op(self, tx):
        """A read of the current version followed by a write of the next one."""
        key = self._pick_unused_key(tx)
        val, vals = self.db[key]
        read_wid = vals[val]
        read_op = Op(read_wid, True, key, val, prev_tx_id=self.wid_to_txid[read_wid])

        write_wid = self._next_wid()
        write_op = Op(write_wid, False, key, self._bump(key, write_wid, tx.tid))
        return [read_op, write_op]

    def generate_op(self, tx):
        choice = random.randrange(0, 100)
        if choice < self.read_ratio:
            return [self.generate_read_op(tx)]
        if choice < self.read_ratio + self.write_ratio:
            return [self.generate_write_op(tx)]
        return self.generate_rmw_op(tx)

    def generate_tx(self, ops_per_transaction):
        tx = Transaction(self.get_next_tid())
        for _ in range(ops_per_transaction):
            for op in self.generate_op(tx):
                tx.add_op(op)
        return tx

    def generate_history(self, num_transactions, ops_per_transaction, num_clients=1):
        """A random serializable history, round-robined over clients at random.

        Returns client id -> list of transactions, in commit order per client.
        """
        clients = {n: [] for n in range(num_clients)}
        clients[0] = [self.insert_keys()]
        for _ in range(num_transactions):
            tx = self.generate_tx(ops_per_transaction)
            clients[random.randrange(num_clients)].append(tx)
        return clients

    def generate_cyclic_history(self, num_transactions, ops_per_transaction):
        """A non-serializable history: two transactions in a WR/RW cycle.

        tx1 writes key 0 and reads key 1 from tx2; tx2 reads key 0 from tx1 and
        writes key 1. Neither can be ordered before the other.
        """
        clients = self.generate_history(num_transactions, ops_per_transaction, 1)

        tx1 = Transaction(self.get_next_tid())
        tx2 = Transaction(self.get_next_tid())
        key_1, key_2 = 0, 1

        tx1_wid = self._next_wid()
        tx1_val = self._bump(key_1, tx1_wid, tx1.tid)
        tx2_wid = self._next_wid()
        tx2_val = self._bump(key_2, tx2_wid, tx2.tid)

        tx1.add_op(Op(tx1_wid, False, key_1, tx1_val))
        tx1.add_op(Op(tx2_wid, True, key_2, tx2_val, prev_tx_id=tx2.tid))  # reads the future
        tx2.add_op(Op(tx1_wid, True, key_1, tx1_val, prev_tx_id=tx1.tid))
        tx2.add_op(Op(tx2_wid, False, key_2, tx2_val))

        clients[0].extend([tx1, tx2])
        return clients

    def generate_ss_history(self):
        """A minimal strong-session-serializable history: tx2 reads tx1's write."""
        init_tx = self.insert_keys()
        tx1 = Transaction(self.get_next_tid())
        tx2 = Transaction(self.get_next_tid())
        key = 0

        tx1_wid = self._next_wid()
        tx1_val = self._bump(key, tx1_wid, tx1.tid)
        tx1.add_op(Op(tx1_wid, False, key, tx1_val))
        tx2.add_op(Op(tx1_wid, True, key, tx1_val, prev_tx_id=tx1.tid))

        return {0: [init_tx, tx1, tx2]}

    def generate_non_ss_history(self):
        """The same shape, but tx2 reads the stale initial version instead of
        tx1's write. Serializable, but not strong-session-serializable: it
        violates read-your-writes within the session."""
        init_tx = self.insert_keys()
        tx1 = Transaction(self.get_next_tid())
        tx2 = Transaction(self.get_next_tid())
        key = 0
        init_wid = self.db[key][1][0]

        tx1_wid = self._next_wid()
        tx1_val = self._bump(key, tx1_wid, tx1.tid)
        tx1.add_op(Op(tx1_wid, False, key, tx1_val))
        tx2.add_op(Op(init_wid, True, key, 0, prev_tx_id=init_tx.tid))  # stale read

        return {0: [init_tx, tx1, tx2]}

    def generate_version_order(self, p_include=1.0):
        """The version order actually observed, optionally thinned.

        `p_include` below 1 drops versions at random, modelling a database that
        exposes only part of its version order. A partial order is still sound:
        King Cobra adds edges only between versions it was told about.
        """
        return {
            key: [v for v in range(val + 1) if random.random() <= p_include]
            for key, (val, _) in self.db.items()
        }


def write_history(log_dir, clients):
    os.makedirs(log_dir, exist_ok=True)
    for client_num, transactions in clients.items():
        path = os.path.join(log_dir, '%d.log' % client_num)
        with open(path, 'wb') as f:
            for tx in transactions:
                f.write(bytes(tx))
        print('  %s: %d transactions' % (path, len(transactions)))


def write_version_order(filename, version_order):
    out = _long(len(version_order))
    for key, versions in version_order.items():
        out += _long(key) + _long(len(versions))
        for version in versions:
            out += _long(version)
    with open(filename, 'wb') as f:
        f.write(out)
    print('  %s: %d keys' % (filename, len(version_order)))


def check_feasible(args):
    """A transaction never touches the same key twice, so it needs at least one
    distinct key per operation -- and an RMW consumes a key for both its read
    and its write. Without this check, key selection would spin forever."""
    if args.mode != 'random' and args.mode != 'cyclic':
        return
    if args.ops_per_tx > args.keys:
        sys.exit('error: --ops-per-tx (%d) exceeds --keys (%d); a transaction '
                 'cannot touch the same key twice' % (args.ops_per_tx, args.keys))
    if args.mode == 'cyclic' and args.keys < 2:
        sys.exit('error: --mode cyclic needs at least 2 keys')


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--mode', default='random',
                   choices=['random', 'cyclic', 'ss', 'non-ss'],
                   help='random: a serializable history. cyclic: appends a '
                        'non-serializable WR/RW cycle. ss / non-ss: minimal '
                        'strong-session-serializable and non- examples. '
                        '(default: random)')
    p.add_argument('--keys', type=int, default=10, help='number of keys (default: 10)')
    p.add_argument('--txns', type=int, default=10, help='number of transactions (default: 10)')
    p.add_argument('--ops-per-tx', type=int, default=5,
                   help='operations per transaction; an RMW counts as one (default: 5)')
    p.add_argument('--read-ratio', type=int, default=50,
                   help='percent of operations that are reads (default: 50)')
    p.add_argument('--write-ratio', type=int, default=35,
                   help='percent that are writes; the remainder are RMWs (default: 35)')
    p.add_argument('--clients', type=int, default=1,
                   help='number of client logs to spread transactions over (default: 1)')
    p.add_argument('--p-include', type=float, default=1.0,
                   help='probability of including each version in the version '
                        'order, for modelling a partially known order (default: 1.0)')
    p.add_argument('--seed', type=int, default=None,
                   help='RNG seed; a random one is chosen and reported if omitted')
    p.add_argument('--log-dir', default='temp_logs',
                   help='directory for the per-client logs (default: temp_logs)')
    p.add_argument('--version-order', default='version_order.vo',
                   help='path for the version order file (default: version_order.vo)')

    args = p.parse_args(argv)
    if args.read_ratio + args.write_ratio > 100:
        p.error('--read-ratio plus --write-ratio must not exceed 100')
    if not 0.0 <= args.p_include <= 1.0:
        p.error('--p-include must be between 0 and 1')
    check_feasible(args)
    return args


def main():
    args = parse_args()
    seed = args.seed if args.seed is not None else random.randrange(sys.maxsize)
    random.seed(seed)

    generator = IncrementHistoryGenerator(args.keys, args.read_ratio, args.write_ratio)
    if args.mode == 'random':
        history = generator.generate_history(args.txns, args.ops_per_tx, args.clients)
    elif args.mode == 'cyclic':
        history = generator.generate_cyclic_history(args.txns, args.ops_per_tx)
    elif args.mode == 'ss':
        history = generator.generate_ss_history()
    else:
        history = generator.generate_non_ss_history()

    write_history(args.log_dir, history)
    write_version_order(args.version_order, generator.generate_version_order(args.p_include))
    print('History generation complete. Mode = %s, seed = %d' % (args.mode, seed))


if __name__ == '__main__':
    main()
