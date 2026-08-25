# Tests

    $ python3 -m pytest tests            # the generator, the oracle, the examples
    $ mvn test                           # the Java units

Neither needs CUDA, MonoSAT, or a database.

## What is covered

`tests/test_generator.py` covers `history_generator.py`: the binary log and
version order formats, the invariants the verifier asserts (unique values per
key, reads resolving to a real write in the named transaction), determinism
under a seed, and the argument guards.

`tests/test_examples.py` pins the claims the README makes about the checked-in
examples, and re-runs the commands in `examples/README.md` to confirm they
still reproduce the committed bytes.

`src/test/java/verifier/VersionOrderTest.java` covers the `.vo` format from the
Java side, so the two ends of the contract are tested independently.

`src/test/java/gpu/ReachabilityMatrixCpuTest.java` covers the reachability
matrix with `GPU_MATRIX=false`, checked against a brute-force transitive
closure computed in the test rather than against the GPU implementation.

`tests/test_end_to_end.py` runs the real verifier over the examples, and is the
only coverage of the version order code in situ. It is skipped until the jar is
built with `./run.sh build`.

## What is not covered

MonoSAT's native library ships here as a Linux x86-64 `.so` only, so the
end-to-end tests can assert a final verdict only for histories that pruning
settles without a solver. Anything beyond that asserts on constraint counts,
which are reported before MonoSAT is invoked. Nothing here covers the GPU path
or the online/database code.

Verification in rounds is uncovered, because it needs the fence transactions
Cobra bench emits and `history_generator.py` does not produce them. Two things
follow. The skip-on-absent-writer path is tested only via a doctored version
order, not via an actual garbage collection. And caching the parsed version
order has no test at all: one-shot mode calls the edge builder exactly once, so
a cached and an uncached implementation are indistinguishable there.

`tests/serializability.py` is a second opinion on the generated histories, not
a test of Cobra's algorithm.

`tests/history_format.py` is written from the Java parsers rather than from the
generator, so a round-trip test cannot pass by sharing a bug with the encoder.
It is still one person's reading of the Java, and the Java parser itself has no
test.
