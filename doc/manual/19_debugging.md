# Debugging {#debugging}

This chapter gives a method to find why a chain does not do what it should, in simulation or on
a board, and the traps that LiteDSP designs meet most often. It assumes the chain builds; for
problems in a netlist, see [Validation](#tool-validation).

## Method {#dbg-method}

Debug from the outside in, and from the cheapest check to the most expensive. The LiteX page on
[debugging a SoC on hardware](https://github.com/enjoy-digital/litex/wiki/Debug-A-SoC-On-Hardware)
gives the general method; for a LiteDSP chain it comes down to the order below.

1. **The link and the identifier.** Start `litex_server` on the bridge and check that the SoC
   answers with the expected identifier: `litedsp_cli info` prints it, with the clock frequency
   and the LiteDSP blocks it finds. A wrong identifier is a wrong bitstream or a wrong `csr.csv`.
2. **The registers.** Read the status registers of the blocks before anything else: saturation
   flags, gains, counters, configuration words. They cost one bus read each and often name the
   faulty block.
3. **The samples.** Capture the stream at the point under suspicion with a capture block and
   look at it on the host: statistics, spectrum, comparison with a model.
4. **The logic.** Only then look at signals with LiteScope, with a narrow capture: a few signals
   of one block, triggered on the event under study.

When a problem appears in simulation, reproduce it in the smallest chain that shows it, then in
the unit test of the faulty block, where the golden model gives the expected output sample by
sample.

## Registers first {#dbg-registers}

Many blocks report their state in status registers, readable from the host with
`litex_server` and a `RemoteClient`, or from firmware through `csr.h`. The table below lists
useful ones; [Register reference](#registers) has them all.

| Block | Registers | Tells |
|---------------------|----------------------------------------|---------------------------------------|
| Gain | `status` | Saturation since the last clear |
| AGC | `gain` | Gain the loop settled to |
| Capture | `status` | Armed, or buffer ready |
| Error counter | `errors`, `total` | Mismatches and compared samples |
| Hamming, BCH decoders | `corrected_total`, `uncorrectable_count` | Channel and decoder health |
| Frame sync | `count` | Detections since clear |
| CORDIC | `latency` | Latency of the built configuration |
| DDC, DUC | `decim_core_config`, `interp_core_config` | Configuration of the rate changer |

A configuration register reads back what the hardware was built with, which is the first thing
to compare with what the software assumes. The host drivers add unit conversions: an NCO
frequency read back in Hz with `NCODriver`, for example ([Host software](#tool-host)).

## Capture blocks {#dbg-capture}

`LiteDSPCapture` plays for samples the role LiteScope plays for logic: it records `depth` I/Q
samples on a trigger and presents them for readout ([Capture](#str-capture) describes the
block). One trap: the memory window (`with_wishbone=True`) reads the buffer without consuming the
output stream, so a capture read only through the window stays in readout and ignores the next
trigger until its output is drained, through `LiteDSPCSRReader` or by a reset of the block. Read
the `status` register before trusting a second capture.

From the host, `litedsp_cli capture` triggers a capture and prints the mean, RMS and peak of the
samples, and saves them with `--npy`; `litedsp_cli spectrum` prints an ASCII spectrum. Insert a
capture where the stream looks wrong, compare its samples with the NumPy model of the chain up to
that point, and move it until the first point that disagrees.

## Error counter {#dbg-counter}

`LiteDSPErrorCounter` compares two I/Q streams sample by sample: a reference and a stream under
test. It consumes a pair only when both inputs are valid, counts the compared samples in `total`
and the mismatches in `errors`, and clears both on `clear`.

It is the core of a self-checking loopback: a PRBS source, a split, the path under test on one
branch, a delay or FIFO on the other, as in `examples/loopback_ber.py`.

It joins its inputs in lock step, so the k-th samples of the two branches always meet, whatever
the latency of each branch. A count of errors equal to `total` means that one branch dropped or
added samples, for example a decimator or a block reset on one branch only; unequal latencies
only reduce the throughput ([Latency mismatch](#dbg-latency)).

## Simulation tools {#dbg-sim}

The unit tests and the examples run blocks in the Migen simulation through `run_stream()` of
`test/common.py`. Its `vcd=` argument writes a waveform file of the whole run, which a viewer such
as GTKWave opens. Its `sink_throttle` and `source_ready_rate` arguments set how often the input
holds `valid` back and how often the output asserts `ready`, and the seeds make a failing pattern
reproducible.

The Verilator runners of `sim/` check the generated Verilog, not the Migen model: `run_lint.py`
lints every registry block and `run_blocks.py` co-simulates blocks against their models with a
chosen seed and backpressure ([Verilator lint and co-simulation](#ver-cosim) gives the commands).

## Common traps {#dbg-traps}

### Migen simulation and Verilog widths {#dbg-widths}

A passing Migen simulation does not prove the Verilog. Migen evaluates an expression with the
widths it infers, while the Verilog may truncate an intermediate sum, shift or product to the
width of its target. Give every intermediate an explicit width, as a `Signal` of the right size,
and run the Verilator co-simulation: it simulates the generated Verilog against the same model.

Slicing and masking differ too. Masking a signed value with `&` widens it by one bit in Migen,
which can shift a field packed next to it; slice the value instead. The capture block packs I and
Q this way.

### Combinational loops between valid and ready {#dbg-loops}

A serial block, one sample per beat, must not make its `sink.ready` depend on its `sink.valid`
([Flow control](#arch-flow)). Joins are where loops appear: the mixer makes the `ready` of one
sink depend on the `valid` of the other. The split never makes its `valid` depend on a `ready`, so
it can feed both sinks of the mixer; a block of your own that joins two inputs must keep the same
rule. A control that changes while
samples are in flight must travel with its beat, as the bypass select does.

### Latency mismatch {#dbg-latency}

Each block declares its latency in samples, or `None` when it depends on the data. Two branches
that meet at a join should carry the same total latency. Every join is lock step, so the samples
still pair correctly, but the shorter branch waits for the longer one: with plain delays, the
throughput falls to about one sample every `1 + d` cycles for a difference of `d`. A netlist
balances its joins itself ([Fan-out, loops and latency balancing](#tool-glue)); a hand-wired
chain inserts the delays itself.

Three cases escape the automatic balancing:

- a block with `None` latency counts as zero, so a branch through a frame-based block, such as a
  PSD accumulator, needs explicit buffering or a timestamp;
- a chain built with `auto_delay=False` only warns about unequal joins;
- a block whose signal delay differs from its pipeline latency, such as the CFR, whose content
  is delayed by its `delay` attribute while `latency` is 1: add that delay by hand on a parallel
  branch. `test/test_latency.py` checks the declarations it can measure
  ([Verification registry](#ver-registry)).

The declared latency must equal the delay, in samples, between an input sample and its output
under free flow; `measure_lag()` of `test/common.py` finds the lag between a reference and a
measured stream.

### A stream that stops {#dbg-stall}

A chain that stops producing output has a beat waiting somewhere: a `valid` without `ready`
downstream, or a `ready` without `valid` upstream. Lock-step joins, such as the error counter, a
combiner or a mixer, wait for all their inputs: a branch that produces fewer samples than the
other, after a decimation for example, stalls the join and everything behind it.

A source that runs freely, such as the NCO, only advances when its sample is accepted, so it
never drops or repeats a sample, but it also stops when its consumer stops. On a board, read the
status registers along the chain, then capture before and after the suspect join.

## Rules for changes {#dbg-rules}

Never edit generated files, such as `build/`, `csr.h`, `csr.csv` or the Verilog: change the
Python and regenerate. Never flash a board or write its SPI flash unless asked: `--load`, which
is volatile, is the default for experiments.

Where to go next: [Verification](#verification) for the test infrastructure, [Benches](#boards)
for the bench host scripts, [Register reference](#registers) for every status register.
