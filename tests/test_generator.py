"""Tests for history_generator.py.

The generator is the only piece of King Cobra that runs without CUDA, MonoSAT,
or a database, so it carries most of the automated coverage. The binary formats
it writes are the contract with the Java verifier, and are read back here by
parsers written from the Java rather than from the generator.
"""

import os

import pytest

from conftest import generator_fails
from history_format import all_transactions, client_logs, parse_version_order
import serializability


# ---------------------------------------------------------------- file format

def test_log_and_version_order_parse(generate):
    out = generate('--keys', 10, '--txns', 20, '--ops-per-tx', 3, '--seed', 1)
    txns = all_transactions(out.history)
    assert txns, 'expected at least one transaction'
    assert parse_version_order(out.version_order)


def test_writes_one_log_per_client(generate):
    out = generate('--keys', 10, '--txns', 30, '--clients', 3, '--seed', 1)
    names = sorted(os.path.basename(p) for p in client_logs(out.history))
    assert names == ['0.log', '1.log', '2.log']


def test_every_transaction_id_is_unique(generate):
    out = generate('--keys', 10, '--txns', 40, '--seed', 3)
    tids = [tid for tid, _ in all_transactions(out.history)]
    assert len(set(tids)) == len(tids)


def test_values_are_unique_per_key(generate):
    """The verifier asserts this when parsing writes: a version order names a
    version by its value, so the mapping back to a write must be unambiguous."""
    out = generate('--keys', 8, '--txns', 40, '--ops-per-tx', 4, '--seed', 4)
    seen = set()
    for _tid, ops in all_transactions(out.history):
        for kind, _wid, key, val, _rf in ops:
            if kind == 'W':
                assert (key, val) not in seen, 'key %d version %d written twice' % (key, val)
                seen.add((key, val))


def test_reads_resolve_to_a_real_write_in_the_named_transaction(generate):
    out = generate('--keys', 8, '--txns', 40, '--ops-per-tx', 4, '--seed', 5)
    txns = all_transactions(out.history)
    writer_of = {}
    for tid, ops in txns:
        for kind, wid, key, val, _rf in ops:
            if kind == 'W':
                writer_of[(key, val)] = (wid, tid)
    for tid, ops in txns:
        for kind, wid, key, val, read_from in ops:
            if kind == 'R':
                assert (key, val) in writer_of, 'read of a version never written'
                assert writer_of[(key, val)] == (wid, read_from)


def test_version_order_only_names_versions_that_exist(generate):
    out = generate('--keys', 8, '--txns', 30, '--seed', 6)
    written = set()
    for _tid, ops in all_transactions(out.history):
        for kind, _wid, key, val, _rf in ops:
            if kind == 'W':
                written.add((key, val))
    for key, versions in parse_version_order(out.version_order).items():
        assert versions == sorted(versions), 'versions must be oldest first'
        for v in versions:
            assert (key, v) in written


def test_rmw_reads_then_writes_the_next_version_of_one_key(generate):
    """With both ratios at zero every operation is an RMW, which must appear as
    a read of the current version followed by a write of the next, on the same
    key."""
    out = generate('--keys', 12, '--txns', 30, '--ops-per-tx', 3,
                   '--read-ratio', 0, '--write-ratio', 0, '--seed', 15)
    init, rest = all_transactions(out.history)[0], all_transactions(out.history)[1:]
    assert all(kind == 'W' for kind, _w, _k, _v, _r in init[1]), 'init writes only'
    assert rest, 'expected transactions beyond the initial one'
    for _tid, ops in rest:
        assert len(ops) % 2 == 0, 'RMWs come in pairs'
        for read, write in zip(ops[0::2], ops[1::2]):
            assert read[0] == 'R' and write[0] == 'W', 'read must precede its write'
            assert read[2] == write[2], 'an RMW touches a single key'
            assert write[3] == read[3] + 1, 'the write must produce the next version'


def test_no_transaction_touches_a_key_twice(generate):
    """Key selection relies on this, and it is why --ops-per-tx is bounded by
    --keys. An RMW is the one exception: it reads and writes the same key."""
    out = generate('--keys', 12, '--txns', 30, '--ops-per-tx', 5, '--seed', 7)
    for _tid, ops in all_transactions(out.history):
        reads = [key for kind, _w, key, _v, _r in ops if kind == 'R']
        writes = [key for kind, _w, key, _v, _r in ops if kind == 'W']
        assert len(reads) == len(set(reads))
        assert len(writes) == len(set(writes))


# ------------------------------------------------------------------ semantics

def test_random_mode_is_serializable(generate):
    out = generate('--mode', 'random', '--keys', 15, '--txns', 40,
                   '--ops-per-tx', 4, '--clients', 2, '--seed', 8)
    assert serializability.is_serializable(out.history)
    assert serializability.is_strong_session_serializable(out.history)


@pytest.mark.parametrize('seed', [1, 2, 3, 4, 5])
def test_random_mode_is_serializable_across_seeds(generate, seed):
    out = generate('--mode', 'random', '--keys', 12, '--txns', 30,
                   '--ops-per-tx', 3, '--clients', 2, '--seed', seed)
    assert serializability.is_serializable(out.history)


def test_cyclic_mode_is_not_serializable(generate):
    out = generate('--mode', 'cyclic', '--keys', 15, '--txns', 20,
                   '--ops-per-tx', 3, '--seed', 9)
    assert not serializability.is_serializable(out.history)


def test_ss_mode_is_strong_session_serializable(generate):
    out = generate('--mode', 'ss', '--keys', 5, '--seed', 10)
    assert serializability.is_serializable(out.history)
    assert serializability.is_strong_session_serializable(out.history)


def test_non_ss_mode_is_serializable_but_not_session_serializable(generate):
    """The distinction CLIENT_ORDER_ON exists to check: the history has no
    cycle on its own, but adding client-order edges creates one, because the
    session reads a value older than one it already wrote."""
    out = generate('--mode', 'non-ss', '--keys', 5, '--seed', 11)
    assert serializability.is_serializable(out.history)
    assert not serializability.is_strong_session_serializable(out.history)


# -------------------------------------------------------------- version order

def test_p_include_thins_the_version_order(generate):
    full = generate('--keys', 30, '--txns', 60, '--ops-per-tx', 3,
                    '--p-include', 1.0, '--seed', 12)
    partial = generate('--keys', 30, '--txns', 60, '--ops-per-tx', 3,
                       '--p-include', 0.3, '--seed', 12)
    full_count = sum(len(v) for v in parse_version_order(full.version_order).values())
    partial_count = sum(len(v) for v in parse_version_order(partial.version_order).values())
    assert partial_count < full_count


def test_p_include_zero_yields_no_versions(generate):
    out = generate('--keys', 10, '--txns', 20, '--p-include', 0.0, '--seed', 13)
    vo = parse_version_order(out.version_order)
    assert vo, 'keys should still be listed'
    assert all(v == [] for v in vo.values())


# ------------------------------------------------------------------ behaviour

def test_a_seed_reproduces_the_same_history(generate):
    first = generate('--keys', 10, '--txns', 25, '--seed', 99)
    second = generate('--keys', 10, '--txns', 25, '--seed', 99)
    for a, b in zip(client_logs(first.history), client_logs(second.history)):
        assert open(a, 'rb').read() == open(b, 'rb').read()
    assert (open(first.version_order, 'rb').read()
            == open(second.version_order, 'rb').read())


def test_different_seeds_differ(generate):
    first = generate('--keys', 10, '--txns', 25, '--seed', 1)
    second = generate('--keys', 10, '--txns', 25, '--seed', 2)
    assert (open(client_logs(first.history)[0], 'rb').read()
            != open(client_logs(second.history)[0], 'rb').read())


def test_every_key_can_be_read(generate):
    """Reads once used a key range one short of the writes, so the last key was
    never read. Regression test for that off-by-one."""
    keys = 12
    out = generate('--keys', keys, '--txns', 400, '--ops-per-tx', 2,
                   '--read-ratio', 100, '--write-ratio', 0, '--seed', 14)
    read_keys = {key for _tid, ops in all_transactions(out.history)
                 for kind, _w, key, _v, _r in ops if kind == 'R'}
    assert read_keys == set(range(keys))


# -------------------------------------------------------------------- guards

def test_ops_per_tx_beyond_keys_is_rejected():
    """Without the guard, key selection spins forever rather than failing."""
    code, err = generator_fails('--keys', 3, '--ops-per-tx', 5)
    assert code != 0
    assert 'ops-per-tx' in err


def test_ratios_over_one_hundred_are_rejected():
    code, err = generator_fails('--read-ratio', 80, '--write-ratio', 40)
    assert code != 0
    assert 'read-ratio' in err


def test_p_include_out_of_range_is_rejected():
    code, err = generator_fails('--p-include', 1.5)
    assert code != 0
    assert 'p-include' in err


def test_unknown_mode_is_rejected():
    code, err = generator_fails('--mode', 'nonsense')
    assert code != 0
    assert 'mode' in err
