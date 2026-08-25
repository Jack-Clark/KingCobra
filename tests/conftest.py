import os
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATOR = os.path.join(REPO_ROOT, 'history_generator.py')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class Generated(object):
    """A generated history plus its version order, on disk."""

    def __init__(self, directory):
        self.dir = str(directory)
        self.history = os.path.join(self.dir, 'history')
        self.version_order = os.path.join(self.dir, 'version_order.vo')


def run_generator(directory, *args):
    """Runs history_generator.py into `directory`. Returns a Generated, or
    raises CalledProcessError with the generator's stderr attached."""
    out = Generated(directory)
    cmd = [sys.executable, GENERATOR,
           '--log-dir', out.history,
           '--version-order', out.version_order] + [str(a) for a in args]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return out


def generator_fails(*args):
    """Runs the generator expecting failure; returns (exit code, stderr)."""
    cmd = [sys.executable, GENERATOR] + [str(a) for a in args]
    p = subprocess.run(cmd, cwd=REPO_ROOT,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stderr.decode('utf-8', 'replace')


@pytest.fixture
def generate(tmp_path):
    """Generates into a fresh temporary directory."""
    counter = {'n': 0}

    def _generate(*args):
        counter['n'] += 1
        target = tmp_path / ('run%d' % counter['n'])
        target.mkdir()
        return run_generator(target, *args)

    return _generate


@pytest.fixture(scope='session')
def repo_root():
    return REPO_ROOT
