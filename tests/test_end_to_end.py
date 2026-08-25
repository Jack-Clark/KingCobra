"""End-to-end runs of the actual verifier.

These are the only tests that execute the Java, so they are the only ones that
cover the version order code path in situ. They are skipped unless the jar has
been built (`./run.sh build`).

The verifier needs MonoSAT's native library whenever constraints survive
pruning, and that library ships here as a Linux x86-64 .so only. Assertions
about a final verdict are therefore limited to cases that pruning settles on
its own; everything else asserts on the constraint counts, which are reported
before any solver is invoked.
"""

import os
import re
import subprocess

import pytest

JAR = os.path.join('target', 'CobraVerifier-0.0.1-SNAPSHOT-jar-with-dependencies.jar')

pytestmark = pytest.mark.skipif(
    not os.path.exists(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), JAR)),
    reason='verifier jar not built; run ./run.sh build')


def write_config(repo_root, tmp_path, name, **overrides):
    """Copies cobra.conf.cpu, replacing the given KEY=value lines."""
    src = os.path.join(repo_root, 'cobra.conf.cpu')
    lines = []
    for line in open(src):
        key = line.split('=')[0].strip()
        if key in overrides:
            lines.append('%s=%s\n' % (key, overrides.pop(key)))
        else:
            lines.append(line)
    for key, value in overrides.items():
        lines.append('%s=%s\n' % (key, value))
    path = tmp_path / name
    path.write_text(''.join(lines))
    return str(path)


def audit(repo_root, config, history):
    """Runs the verifier. Returns (stdout+stderr, constraints before/after prune)."""
    env = dict(os.environ)
    env.pop('COBRA_HOME', None)
    env.pop('CUDA_PATH', None)
    p = subprocess.run(['bash', 'run.sh', 'mono', 'audit', config, history],
                       cwd=repo_root, env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode('utf-8', 'replace')

    def count(pattern):
        m = re.search(pattern + r' = (\d+)', out)
        return int(m.group(1)) if m else None

    return out, count(r'Before PRUNE #constraint\[1\]'), count(r'After PRUNE #constraint\[2\]')


def vo_edges(out):
    """Number of VO edges the verifier reported adding."""
    m = re.search(r'VO edges added = (\d+)', out)
    return int(m.group(1)) if m else None


HISTORY = os.path.join('examples', 'random-serializable', 'history')
VERSION_ORDER = os.path.join('examples', 'random-serializable', 'version_order.vo')


def test_accepts_the_serializable_example(repo_root, tmp_path):
    config = write_config(repo_root, tmp_path, 'vo.conf',
                          VERSION_ORDER_ON='true', VERSION_ORDER_PATH=VERSION_ORDER)
    out, _before, after = audit(repo_root, config, HISTORY)
    assert 'ACCEPT' in out, out[-2000:]
    assert after == 0


def test_loads_the_version_order(repo_root, tmp_path):
    config = write_config(repo_root, tmp_path, 'vo.conf',
                          VERSION_ORDER_ON='true', VERSION_ORDER_PATH=VERSION_ORDER)
    out, _before, _after = audit(repo_root, config, HISTORY)
    assert 'Version order loaded: 20 keys' in out, out[-2000:]


def test_missing_version_order_file_fails_loudly(repo_root, tmp_path):
    """A missing file used to yield an empty version order, so the run silently
    became stock Cobra. Asking for a version order that cannot be loaded is a
    configuration error and must stop the run."""
    config = write_config(repo_root, tmp_path, 'absent.conf',
                          VERSION_ORDER_ON='true',
                          VERSION_ORDER_PATH='does/not/exist.vo')
    out, _before, _after = audit(repo_root, config, HISTORY)
    assert 'ACCEPT' not in out, 'a degraded run must not report a verdict'
    assert 'does/not/exist.vo' in out
    assert 'VERSION_ORDER_ON' in out, 'the error should say how to proceed without one'


def test_skips_edges_whose_writer_is_absent(repo_root, tmp_path):
    """A version order may name a write this verifier has not seen -- in rounds
    mode because it was collected, or because the order came from a database and
    covers more than the log. That used to raise a NullPointerException; the
    edge is now skipped and the count reported."""
    import struct

    source = os.path.join(repo_root, VERSION_ORDER)
    buf = open(source, 'rb').read()
    (count,) = struct.unpack_from('>q', buf, 0)
    out_bytes = struct.pack('>q', count)
    i = 8
    for _ in range(count):
        key, num = struct.unpack_from('>qq', buf, i)
        i += 16
        versions = list(struct.unpack_from('>%dq' % num, buf, i))
        i += 8 * num
        # Splice in a version that no write ever produced, so the real versions
        # after it have a predecessor the verifier cannot resolve.
        versions = versions[:1] + [10 ** 9] + versions[1:]
        out_bytes += struct.pack('>qq', key, len(versions))
        out_bytes += struct.pack('>%dq' % len(versions), *versions)

    doctored = tmp_path / 'doctored.vo'
    doctored.write_bytes(out_bytes)

    config = write_config(repo_root, tmp_path, 'doctored.conf',
                          VERSION_ORDER_ON='true', VERSION_ORDER_PATH=str(doctored))
    out, _before, _after = audit(repo_root, config, HISTORY)

    assert 'NullPointerException' not in out, out[-2000:]
    assert 'VO edges skipped' in out, out[-2000:]


def test_version_order_removes_the_constraints_pruning_leaves_behind(repo_root, tmp_path):
    """The reason King Cobra exists: on this history, version order takes the
    residue after pruning to zero, so no solver call is needed at all."""
    without = write_config(repo_root, tmp_path, 'novo.conf', VERSION_ORDER_ON='false')
    with_vo = write_config(repo_root, tmp_path, 'vo.conf',
                           VERSION_ORDER_ON='true', VERSION_ORDER_PATH=VERSION_ORDER)

    _o1, before_off, after_off = audit(repo_root, without, HISTORY)
    _o2, before_on, after_on = audit(repo_root, with_vo, HISTORY)

    assert before_off == before_on, 'both runs should start from the same constraints'
    assert after_off > 0, 'without version order some constraints should survive pruning'
    assert after_on == 0, 'with version order pruning should settle everything'


def test_all_vo_edges_reaches_the_same_verdict(repo_root, tmp_path):
    """The closure and direct-predecessor forms express the same reachability,
    so they must not disagree."""
    direct = write_config(repo_root, tmp_path, 'direct.conf',
                          VERSION_ORDER_ON='true', ALL_VO_EDGES='false',
                          VERSION_ORDER_PATH=VERSION_ORDER)
    closure = write_config(repo_root, tmp_path, 'closure.conf',
                           VERSION_ORDER_ON='true', ALL_VO_EDGES='true',
                           VERSION_ORDER_PATH=VERSION_ORDER)
    out_direct, _b1, after_direct = audit(repo_root, direct, HISTORY)
    out_closure, _b2, after_closure = audit(repo_root, closure, HISTORY)

    assert ('ACCEPT' in out_direct) == ('ACCEPT' in out_closure)
    assert after_direct == after_closure == 0


def test_all_vo_edges_materialises_strictly_more_edges(repo_root, tmp_path):
    """ALL_VO_EDGES draws an edge from every earlier version's writer rather
    than the immediate predecessor alone. Same reachability, more edges -- and
    if the two ever produced the same count, one of the branches would be
    doing nothing."""
    direct = write_config(repo_root, tmp_path, 'direct.conf',
                          VERSION_ORDER_ON='true', ALL_VO_EDGES='false',
                          VERSION_ORDER_PATH=VERSION_ORDER)
    closure = write_config(repo_root, tmp_path, 'closure.conf',
                           VERSION_ORDER_ON='true', ALL_VO_EDGES='true',
                           VERSION_ORDER_PATH=VERSION_ORDER)
    out_direct, _b1, _a1 = audit(repo_root, direct, HISTORY)
    out_closure, _b2, _a2 = audit(repo_root, closure, HISTORY)

    direct_edges, closure_edges = vo_edges(out_direct), vo_edges(out_closure)
    assert direct_edges and closure_edges, 'both runs should report an edge count'
    assert closure_edges > direct_edges, '%d vs %d' % (closure_edges, direct_edges)


def test_rejects_the_cyclic_example(repo_root, tmp_path):
    """Rejection at the known-graph stage is upstream Cobra's `assert false`,
    so the process dies after printing the offending transactions rather than
    returning a verdict. Asserted here as it actually behaves."""
    config = write_config(repo_root, tmp_path, 'cyclic.conf',
                          VERSION_ORDER_ON='true',
                          VERSION_ORDER_PATH=os.path.join(
                              'examples', 'cyclic-violation', 'version_order.vo'))
    out, _before, _after = audit(
        repo_root, config, os.path.join('examples', 'cyclic-violation', 'history'))
    assert 'ACCEPT' not in out
    assert 'AssertionError' in out or 'REJECT' in out, out[-2000:]
