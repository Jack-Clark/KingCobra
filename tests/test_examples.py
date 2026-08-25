"""Tests for the histories checked in under examples/.

They are what a new reader runs first, and the README makes specific claims
about each one. These pin those claims, and confirm the files still match the
commands documented in examples/README.md.
"""

import os
import subprocess
import sys

import pytest

from conftest import run_generator
from history_format import all_transactions, client_logs, parse_version_order
import serializability


def example(repo_root, name):
    class E(object):
        dir = os.path.join(repo_root, 'examples', name)
        history = os.path.join(dir, 'history')
        version_order = os.path.join(dir, 'version_order.vo')
    return E


def test_random_example_is_serializable(repo_root):
    e = example(repo_root, 'random-serializable')
    assert serializability.is_serializable(e.history)
    assert serializability.is_strong_session_serializable(e.history)


def test_cyclic_example_is_not_serializable(repo_root):
    """It must fail on its own merits, not only once client order is added --
    otherwise it would demonstrate a session violation, not a cycle."""
    e = example(repo_root, 'cyclic-violation')
    assert not serializability.is_serializable(e.history)


def test_examples_parse_and_are_internally_consistent(repo_root):
    for name in ('random-serializable', 'cyclic-violation'):
        e = example(repo_root, name)
        txns = all_transactions(e.history)
        assert txns
        written = {(k, v) for _t, ops in txns
                   for kind, _w, k, v, _r in ops if kind == 'W'}
        for key, versions in parse_version_order(e.version_order).items():
            for v in versions:
                assert (key, v) in written, '%s names a version never written' % name


@pytest.mark.parametrize('name,args', [
    ('random-serializable',
     ['--mode', 'random', '--keys', '20', '--txns', '50', '--ops-per-tx', '4',
      '--clients', '2', '--seed', '20210823']),
    ('cyclic-violation',
     ['--mode', 'cyclic', '--keys', '20', '--txns', '20', '--ops-per-tx', '4',
      '--seed', '20210823']),
])
def test_examples_match_their_documented_commands(repo_root, tmp_path, name, args):
    """The commands in examples/README.md must still reproduce the checked-in
    bytes, so the examples cannot drift from their documentation."""
    regenerated = run_generator(tmp_path / name, *args)
    committed = example(repo_root, name)

    got = client_logs(regenerated.history)
    want = client_logs(committed.history)
    assert [os.path.basename(p) for p in got] == [os.path.basename(p) for p in want]
    for a, b in zip(got, want):
        assert open(a, 'rb').read() == open(b, 'rb').read(), '%s/%s differs' % (name, os.path.basename(b))
    assert (open(regenerated.version_order, 'rb').read()
            == open(committed.version_order, 'rb').read())
