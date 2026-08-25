# Worked examples

Two small histories with matching version orders, checked in so King Cobra can be run immediately
after a build. Both are deterministic: the commands below reproduce them byte for byte.

## `random-serializable/`

51 transactions over 2 clients, 20 keys, a mix of reads, writes, and read-modify-writes. Contains
no anomaly; the verifier should accept it.

    $ ./history_generator.py --mode random --keys 20 --txns 50 --ops-per-tx 4 --clients 2 \
        --seed 20210823 \
        --log-dir examples/random-serializable/history \
        --version-order examples/random-serializable/version_order.vo

Run it with the config that is already pointed at this example:

    $ ./run.sh mono audit ./cobra.conf.cpu ./examples/random-serializable/history

On this history the version order takes the post-pruning constraint count to zero, so the
verifier accepts without calling MonoSAT at all. With `VERSION_ORDER_ON=false`, five constraints
survive and the solver is needed.

## `cyclic-violation/`

23 transactions over 1 client, ending in two transactions that form a WR/RW cycle: `tx1` writes
key 0 and reads key 1 from `tx2`, while `tx2` reads key 0 from `tx1` and writes key 1. Neither can
be ordered before the other, so the history is not serializable and the verifier should reject it.

    $ ./history_generator.py --mode cyclic --keys 20 --txns 20 --ops-per-tx 4 \
        --seed 20210823 \
        --log-dir examples/cyclic-violation/history \
        --version-order examples/cyclic-violation/version_order.vo

To run it, copy `cobra.conf.cpu` and set
`VERSION_ORDER_PATH=examples/cyclic-violation/version_order.vo`, then:

    $ ./run.sh mono audit ./<your config> ./examples/cyclic-violation/history

The verifier prints the two transactions forming the cycle and then exits with an
`AssertionError`, which is how upstream Cobra signals rejection at that stage. Expected, not a
crash.

## Scaling up

Neither example is large enough to show a timing difference. For that, generate a bigger history
and compare the same history with `VERSION_ORDER_ON` on and off — for example:

    $ ./history_generator.py --keys 1000 --txns 10000 --ops-per-tx 8 --seed 1

See the [file formats](../README.md#file-formats) section for what the `.log` and `.vo` files
contain.
