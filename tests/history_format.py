"""Readers for the two binary formats, written from the verifier's Java parsers
rather than from history_generator.py.

Deliberately independent of the generator: if both sides shared an encoder the
round-trip tests would pass however wrong that encoder was. The reference is
AbstractVerifier.ExtractClientLogFromStream and verifier/VersionOrder.java.
"""

import glob
import os
import struct

_LONG = struct.Struct('>q')


def _rd(buf, i):
    return _LONG.unpack_from(buf, i)[0], i + 8


def parse_log(path):
    """Returns [(txn id, [op, ...])], where op is (kind, wid, key, val, read_from)."""
    buf = open(path, 'rb').read()
    i, txns = 0, []
    while i < len(buf):
        marker = buf[i:i + 1]
        if marker != b'S':
            raise ValueError('expected S at byte %d of %s, got %r' % (i, path, marker))
        i += 1
        tid, i = _rd(buf, i)
        ops = []
        while buf[i:i + 1] != b'C':
            kind = buf[i:i + 1]
            i += 1
            if kind == b'W':
                wid, i = _rd(buf, i)
                key, i = _rd(buf, i)
                val, i = _rd(buf, i)
                ops.append(('W', wid, key, val, None))
            elif kind == b'R':
                read_from, i = _rd(buf, i)
                wid, i = _rd(buf, i)
                key, i = _rd(buf, i)
                val, i = _rd(buf, i)
                ops.append(('R', wid, key, val, read_from))
            else:
                raise ValueError('unknown op %r at byte %d of %s' % (kind, i - 1, path))
        i += 1
        commit_tid, i = _rd(buf, i)
        if commit_tid != tid:
            raise ValueError('S/C transaction id mismatch: %d vs %d' % (tid, commit_tid))
        txns.append((tid, ops))
    return txns


def parse_version_order(path):
    """Returns {key: [version, ...]}, versions oldest first."""
    buf = open(path, 'rb').read()
    i = 0
    count, i = _rd(buf, i)
    version_order = {}
    for _ in range(count):
        key, i = _rd(buf, i)
        num, i = _rd(buf, i)
        versions = []
        for _ in range(num):
            v, i = _rd(buf, i)
            versions.append(v)
        if key in version_order:
            raise ValueError('duplicate key %d' % key)
        version_order[key] = versions
    if i != len(buf):
        raise ValueError('%d trailing bytes in %s' % (len(buf) - i, path))
    return version_order


def client_logs(history_dir):
    """The .log files of a history directory, in the order the verifier reads them."""
    return sorted(glob.glob(os.path.join(history_dir, '*.log')))


def all_transactions(history_dir):
    txns = []
    for path in client_logs(history_dir):
        txns.extend(parse_log(path))
    return txns
