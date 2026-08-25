# King Cobra

King Cobra is a fork of the [Cobra verifier](https://github.com/DBCobra/CobraHome) that checks
[serializability](https://en.wikipedia.org/wiki/Serializability) of a transaction history, extended
to exploit information a database can cheaply reveal about itself.

Cobra reconstructs a serialization order from a history alone. Where the history does not determine
the order of two writes to the same key, Cobra emits a *constraint* and hands the choice to a SAT
solver. Those constraints dominate the solving cost. King Cobra's observation is that a database
usually knows its own write order and can simply say so — and a stated version order collapses each
of those choices into a single edge.

On top of that, King Cobra makes client-order edges optional, so the verifier can be pointed at
session guarantees weaker than full serializability, and ships a history generator so the whole
thing can be exercised without a database.

Everything below the [Cobra verifier](#cobra-verifier) heading is upstream Cobra, unchanged.


## What King Cobra adds

### Version order edges

A **version order** lists, for each key, the sequence of values that key took, oldest first. Given
one, every pair of writes to the same key has a known direction, so King Cobra adds a `VO` edge in
that direction instead of leaving a constraint for the solver.

Enable it with `VERSION_ORDER_ON=true` and point `VERSION_ORDER_PATH` at a version order file.
If that file cannot be read the run stops rather than continuing without it, so a degraded result
is never mistaken for a good one.

`ALL_VO_EDGES` controls how densely the order is materialised. With it off (the default), each
write gets one edge, from the writer of the immediately preceding version. With it on, each write
gets an edge from the writer of *every* preceding version — the transitive closure. Both express
the same reachability relation; the closure trades a much larger graph for shorter paths.

A version order may be **partial**. Versions it omits simply get no edges, so a database that can
only expose part of its write order still helps. `history_generator.py --p-include` models this.
The same tolerance covers a version whose writer the verifier has not seen — collected in rounds
mode, or outside the log entirely: that edge is skipped and the count reported as
`VO edges skipped`. Fewer edges means weaker checking, never a wrong answer.

### Optional client-order edges

Upstream Cobra always adds a client-order (`CO`) edge between consecutive transactions from the
same client, which bakes session ordering into the definition being checked. `CLIENT_ORDER_ON=false`
suppresses those edges while still recording the client links, so histories can be checked against
weaker session guarantees. `history_generator.py --mode ss|non-ss` produces a minimal pair of
histories that differ only in that respect.

### History generator

`history_generator.py` writes synthetic histories in the binary format the verifier's log parser
expects, together with a matching version order — no database, no benchmark harness, no GPU:

    $ ./history_generator.py --keys 20 --txns 50 --ops-per-tx 4 --clients 2 --seed 20210823 \
        --log-dir temp_logs --version-order version_order.vo

    $ ./history_generator.py --help    # all options

Values increase by one per write, so a value doubles as a version number and is unique per key.
King Cobra relies on that uniqueness to map a version named in the version order back to the write
that produced it (see [Known limitations](#known-limitations)).

Modes:

| `--mode`  | History |
| --------- | ------- |
| `random`  | A random serializable history (default). |
| `cyclic`  | The same, plus two transactions in a WR/RW cycle — not serializable. |
| `ss`      | A minimal strong-session-serializable history: `tx2` reads `tx1`'s write. |
| `non-ss`  | The same shape, but `tx2` reads the stale initial version — serializable, but violates read-your-writes within the session. |

A given `--seed` always reproduces the same history.


## Configuration

King Cobra adds four keys to the Cobra config file:

| Key | Default | Meaning |
| --- | ------- | ------- |
| `VERSION_ORDER_ON`   | `false`            | Load a version order and add `VO` edges. |
| `VERSION_ORDER_PATH` | `version_order.vo` | Path to the version order file, relative to the working directory. |
| `ALL_VO_EDGES`       | `false`            | Materialise the transitive closure of `VO` edges rather than direct-predecessor edges only. |
| `CLIENT_ORDER_ON`    | `true`             | Emit client-order (`CO`) edges. |

Three ready-made configs are included:

| File | Version order | Client order | Purpose |
| ---- | ------------- | ------------ | ------- |
| `cobra.conf.version-order` | on  | on  | Version order on an ordinary serializability check. Pre-pointed at `examples/random-serializable`. |
| `cobra.conf.session-vo`    | on  | off | Session-guarantee checking, with version order. |
| `cobra.conf.session-novo`  | off | off | The same, without version order — the baseline for the pair above. |
| `cobra.conf.cpu`           | on  | on  | As `cobra.conf.version-order`, but with `GPU_MATRIX=false`. The starting point on a machine without CUDA. |

Note that `cobra.conf.version-order` sets `MAX_INFER_ROUNDS=1` while the two session configs set
`5`; do not compare timings across that boundary without equalising it first.

The config parser is upstream Cobra's. It splits every line on `=` and asserts exactly two fields,
so config files cannot contain comments or blank lines.


## Running without a GPU

Upstream Cobra requires CUDA. King Cobra does not: set `GPU_MATRIX=false` and the
verifier uses the CPU reachability path instead. `cobra.conf.cpu` is that config.

    $ ./run.sh build     # skips the CUDA step when nvcc is absent
    $ ./run.sh mono audit ./cobra.conf.cpu ./examples/random-serializable/history

`COBRA_HOME` is optional on this path; `run.sh` warns and carries on without it.

One platform caveat. MonoSAT is invoked whenever constraints survive pruning, and its native
library ships here as a Linux x86-64 `.so` only, so on other platforms such a run ends in an
`UnsatisfiedLinkError`. A history that pruning settles completely never reaches the solver and
runs anywhere.

The checked-in example happens to show the version order's effect at that boundary:

| `examples/random-serializable` | constraints before pruning | after pruning | outcome |
| --- | --- | --- | --- |
| `VERSION_ORDER_ON=false` | 234 | 5 | MonoSAT required |
| `VERSION_ORDER_ON=true`  | 234 | 0 | accepted without a solver call |

The version order is not there to avoid MonoSAT; it is there to cut the constraints handed to
it, which is where Cobra's verification cost concentrates. Reaching zero on this small history
is a side effect of that. On larger histories pruning alone often reaches zero, and the version
order then changes nothing — its value is on the histories where it does not.


## Running with a GPU

Cobra's reachability matrix can run on the GPU, which is how the paper's numbers were produced.
King Cobra inherits that path unchanged and it is enabled the same way: `GPU_MATRIX=true`, which
`cobra.conf.version-order`, `cobra.conf.session-vo`, and `cobra.conf.session-novo` already set.

The GPU path needs more than a GPU, and the requirements are stricter than the CPU path's:

| Requirement | Why |
| --- | --- |
| An NVIDIA GPU and matching driver | `include/gpu_GPUmm.cu` is CUDA |
| The CUDA toolkit, including `nvcc` | `jni.sh` compiles the kernels with it |
| cuBLAS and cuSPARSE | linked by `jni.sh`; both ship with the toolkit |
| **Java 8** | `jni.sh` accepts only `1.7` or `1.8` and aborts on anything else |
| `JAVA_HOME` and `CUDA_PATH` | `jni.sh` exits immediately if either is empty |
| `COBRA_HOME`, pointing at a checkout of [CobraHome](https://github.com/DBCobra/CobraHome) | `run.sh` sources `$COBRA_HOME/env.sh`, which is expected to supply `CUDA_ARCH` and the `fail` helper |

Note the Java constraint. The CPU path builds and runs on Java 8 through 17, but the GPU path
needs Java 8 specifically, because `jni.sh` generates the JNI header with `javac -h` and gates on
the version string.

Upstream tested on an AWS EC2 `p3.2xlarge` with the `Deep Learning Base AMI (Ubuntu 18.04)`,
CUDA 10.0.130, and Java 1.8.0. That instance type gives you a V100, so `CUDA_ARCH` should be
`-arch=sm_70`; set it to match your own card if you use a different one. It is read from
`env.sh`, not from anything in this repository.

    $ export COBRA_HOME=/path/to/CobraHome
    $ export JAVA_HOME=/usr/lib/jvm/java-8-openjdk-amd64
    $ export CUDA_PATH=/usr/local/cuda
    $ ./run.sh build

You do not need cuDNN, despite appearances: `jni.sh` adds `-I`/`-L` flags for
`$HOME/scratch/cudnn/cuda`, but `gpu_GPUmm.cu` includes only `cuda_runtime.h`, `cublas_v2.h`,
and `cusparse.h`. The flags are vestigial and harmless when the directory does not exist.

A successful build leaves `include/libgpumm.so`, which the JVM loads via
`-Djava.library.path=include/`. If it is missing you get `UnsatisfiedLinkError: no gpumm in
java.library.path`; see [Troubleshooting](#troubleshooting).

Two limits worth knowing before a long run. `MAX_N` in `include/gpu_GPUmm.cu` (line 34,
`30000ul`) pre-allocates the matrix and therefore caps transactions per round — raise it and
rebuild for larger histories. And only one verifier can hold the GPU at a time; a second one
fails with `CUDA: out of memory`. Both are covered under [Troubleshooting](#troubleshooting).

To benchmark the GPU configuration with `bench_mono.py`, re-enable the `[True, True, True, True]`
row in its optimisation list, which is commented out.


## Worked examples

Two histories are checked in under `examples/`, each a history directory plus its version order:

    examples/random-serializable/   # 51 transactions over 2 clients, serializable
    examples/cyclic-violation/      # 23 transactions over 1 client, contains a WR/RW cycle

Both were produced with `--seed 20210823`; the exact commands are in
[`examples/README.md`](examples/README.md), so either can be regenerated or scaled up.

After building (see [Step 1](#step1)), run the serializable one:

    $ ./run.sh mono audit ./cobra.conf.version-order ./examples/random-serializable/history

To check the same history without version order, so the effect is visible, copy
`cobra.conf.version-order` and set `VERSION_ORDER_ON=false`.

To run against the violation example, change `VERSION_ORDER_PATH` in your config to
`examples/cyclic-violation/version_order.vo` and pass that example's history directory.

The verifier rejects it, but be ready for how that looks: upstream Cobra signals rejection at
the known-graph stage with a bare `assert false`, so after printing the two transactions that
form the cycle the process exits with an `AssertionError` rather than a verdict line. That is
the expected outcome, not a crash.


## File formats

Both formats are big-endian, with every integer 8 bytes. `history_generator.py` writes them and
`AbstractVerifier` / `AbstractLogVerifier` read them.

### History log

One file per client, named `<client>.log`, in a single directory; the verifier picks up every
`.log` file it finds there. Each file is a concatenation of transactions:

    'S' <txn id>                      transaction start
      'W' <write id> <key> <value>       write
      'R' <read-from txn id> <write id> <key> <value>   read
    'C' <txn id>                      transaction commit, same id as the start

Transactions appear in commit order within a file, and that order is the client order.

### Version order

    <number of keys>
    per key:  <key> <number of versions> <version> ...

Versions are listed oldest first and are the values themselves, not indices. Keys or versions may
be omitted; the order is treated as partial.


## Known limitations

These are known and unaddressed. They are worth reading before trusting a measurement.

* **Verification in rounds is untested.** The version order path is exercised only in one-shot
  mode. Rounds mode needs the fence transactions that Cobra bench emits, which
  `history_generator.py` does not produce, so nothing here runs it. The code handles a
  collected predecessor by skipping the edge and reporting `VO edges skipped`, but that path
  has never been executed.
* **Values must be unique per key.** The version order identifies a version by its value, and
  `AbstractVerifier` asserts uniqueness when parsing writes. Histories from `history_generator.py`
  satisfy this by construction; arbitrary histories, including those from Cobra bench, may not.
* **MonoSAT is Linux x86-64 only here.** `include/libmonosat.so` is a Linux binary and the jar
  bundles no others, so any history whose constraints survive pruning can only be verified on
  that platform.

## Tests

    $ python3 -m pytest tests    # the generator, an independent oracle, the examples, end-to-end runs
    $ mvn test                   # the Java units

Neither needs CUDA, MonoSAT, or a database. See [`tests/README.md`](tests/README.md) for what is
and is not covered.

---

# Cobra verifier

The rest of this document is the upstream Cobra verifier documentation, which still applies to
King Cobra: the build, the two verification modes, and the reproduction instructions are unchanged.

Cobra verifier is a component of the [Cobra project](https://github.com/DBCobra/CobraHome).
Cobra verifier checks serializability of a set of transactions (called history). The Cobra paper
[[1]](#cobrapaper) defines the problem and gives context.

## How to install and run Cobra verifier

The following steps build Cobra verifier and run it on existing histories or the histories generated
by [Cobra bench](https://github.com/DBCobra/CobraBench).

Cobra verifier requires a NVIDIA GPU and a corresponding environment (GPU drivers, libraries, and a
NVCC compiler), for example an AWS EC2 `p3.2xlarge` instance with `Deep Learning Base AMI (Ubuntu 18.04)`.
The King Cobra additions do not need a GPU; see [Running without a GPU](#running-without-a-gpu).

This tutorial has been tested on Ubuntu 18.04, Java v1.8.0, and CUDA v10.0.130. The build also works
on Java 11 and later.

### Step 0: Setup environment

Please see the README in [CobraHome](https://github.com/DBCobra/CobraHome) and
run its commands to prepare Cobra's environment.

### <a name="step1"/> Step 1: Build Cobra verifier

Install required packages:

    $ sudo apt install libgmpxx4ldbl maven wcstools

Add [MonoSAT](http://www.cs.ubc.ca/labs/isd/Projects/monosat/) as a library:

    $ cd $COBRA_HOME/CobraVerifier/
    $ mvn install:install-file -Dfile=./monosat/monosat.jar -DgroupId=monosat \
      -DartifactId=monosat -Dversion=1.4.0 -Dpackaging=jar -DgeneratePom=true

Build Cobra verifier:

    $ ./run.sh build

Now ensure that the verifier built successfully:

    $ ./run.sh mono audit RANDOMSTRING

The verifier should produce an error message:

> [ERROR] Config file \<RANDOMSTRING\> not found

### <a name="step2" /> Step 2: Run Cobra verifier

Cobra verifier has two modes for checking serializability:

  * **One-shot verification**: load the history as a whole and run Cobra's verification algorithm
  * **Verification in rounds**: load a subset of the history, run the verification algorithm on the subset, garbage collect outdated transactions, and load more transactions from the history

#### (i) one-shot verification

Run the verifier in one-shot mode:

    $ ./run.sh mono audit ./cobra.conf.default [history]
    # for example, replace [history] with ./CobraLogs/one-shot-10k/twitter-10000/

The `[history]` is a history folder; you can get a history from either [CobraLogs](https://github.com/DBCobra/CobraLogs) or running [Cobra bench](https://github.com/DBCobra/CobraBench).

#### (ii) verification in rounds

Run the verifier in rounds mode:

    $ ./run.sh mono continue ./cobra.conf.default [history]
    # for example, replace [history] with ./CobraLogs/scaling/twitter-100000/

Note that verification in rounds needs _fence transactions_ which are synchronization transactions issued by database clients.
This requires that the history is generated by [Cobra bench](https://github.com/DBCobra/CobraBench),
whose database library issues fence transactions.

## Reproduce results

In the Cobra paper [[1]](#cobrapaper), the verifier is evaluated on various workloads and compared
with different baselines. To reproduce Figures 5-9 in Section 6.1 and 6.2, please see
[instructions to reproduce experiments](reproduce_results.md).

## <a name="troubleshooting" /> Troubleshooting

#### Exception in thread "main" java.lang.UnsatisfiedLinkError: no gpumm in java.library.path

This exception means that Cobra's GPU library is not correctly built or linked. Please run the commands below and look for error messages.

    $ cd $COBRA_HOME/CobraVerifier/
    $ ./run.sh build

#### <a name="OOM" /> CUDA: out of memory

There are three reasons why Cobra verifier reports this error.

* Another Cobra verifier instance is running. Please stop the running verifier instance before launching another.

* The current task requires more GPU memory than the default allocation. You can allocate more GPU memory to Cobra by updating the file `$COBRA_HOME/CobraVerifier/include/gpu_GPUmm.cu` line 34 (`#define MAX_N 30000ul`) to a larger number (say `38000ul`), and rebuild the verifier (`./run.sh build`).

* The required GPU memory exceeds the physical GPU memory. In this case, Cobra cannot verify this history with the current GPU.


## <a name="cobrapaper" /> Reference

[1] Cheng Tan, Changgeng Zhao, Shuai Mu, and Michael Walfish. Cobra: Making Transactional Key-Value Stores Verifiably Serializable. OSDI 2020.


## License

MIT, as inherited from upstream Cobra. See [LICENSE](LICENSE).
