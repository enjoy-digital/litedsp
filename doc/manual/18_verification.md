# Verification {#verification}

This chapter describes how LiteDSP checks its blocks before any bitstream: the golden models, the
randomized backpressure, the Verilator lint and co-simulation, the coverage, the formal proofs of
the stream plumbing, the quality characterization and the implementation flows. It is for
contributors who change a block and for integrators who want to know what a block's status
means and how to reproduce a check.

The checks produce evidence, not hardware results: no run on a board is recorded in the
repository. The [status table](#intro-status) states what each family has been through, and the
numbers the flows record are in [Performance and resources](#performance).

## Strategy at a glance {#ver-glance}

A DSP block can fail in ways that a quick simulation does not show: an off-by-one rounding, a
sample lost on a rare stall, a product truncated by the Verilog emitter, a path that does not
close timing on another vendor's device. LiteDSP therefore checks each block at several levels,
each one cheap enough to run on every change or every night.

| Level | What runs | Reference | Tool | When |
|------------------------------|-----------------------------------|------------------------|--------------------|----------------|
| Unit tests | Each block in the Migen simulation | NumPy golden models | `unittest` | Every push |
| Policy ratchets | Registry, parameters, latency, bypass | Rules of the block contract | `unittest` | Every push |
| Lint | Verilog of every registry block | Verilator warnings | Verilator | Every push |
| Co-simulation | Verilog of the model-backed blocks | Same golden models, bit-exact | Verilator | Push, nightly |
| Coverage | The co-simulation, instrumented | 90 % of lines per block | Verilator | Nightly |
| Property tests | Sampled constructor parameters | Golden models | Hypothesis | Nightly |
| Formal | The plumbing blocks | Stream properties | SymbiYosys | Nightly |
| Characterization | Quality metrics | Recorded baselines | NumPy | Nightly |
| Implementation | Synthesis, place and route | Recorded budgets | Yosys, nextpnr, Vivado | Push, nightly, manual |

The next sections take these levels in order. [Continuous integration map](#ver-ci) lists the
workflows that run them.

## Golden models and randomized backpressure {#ver-golden}

Most blocks with deterministic arithmetic have a NumPy model in `test/models.py` that reproduces
its fixed-point behaviour bit for bit: same products, same rounding position, same saturation.
The helpers of `test/common.py` (`np_rounded`, `np_saturated`, `np_scaled`) mirror the gateware
helpers of `litedsp/common.py`, so a model is written with the same steps as the block.

A test drives the block in the Migen simulation and compares its output with the model. Where
rounding legitimately differs, for example a different but valid order of operations, the test
compares with a signal-to-noise threshold instead (`assert_snr`). A block without a model, such
as the DDC or the stream plumbing, is tested against values computed in its test. Each test lives in
`test/test_<block>.py`, as the contribution checklist of `CONTRIBUTING.md` asks.

Every test runs under randomized backpressure. The `run_stream` harness inserts idle cycles on
the input with a probability (`sink_throttle`, 0.25 by default) and lowers `ready` on the output
(`source_ready_rate`, 0.75 by default). A block that drops, duplicates or reorders a sample on a
stall fails the comparison. The seeds derive from `LITEDSP_SEED`, so a failure is reproducible.

```sh
# The whole suite (golden models, integration, policies).
python3 -m unittest discover -s test -v
# One block, with another backpressure pattern.
LITEDSP_SEED=3 python3 -m unittest test.test_agc -v
```

The capture below is the AGC test file, run on the default branch with Python 3.10. It covers the
three feedback delays, each bit-exact against `agc_model` under backpressure.

```console
$ python3 -m unittest test.test_agc -v
test_bit_exact_under_backpressure (test.test_agc.TestAGC) ... ok
test_converges (test.test_agc.TestAGC) ... ok
test_delayed_feedback_bit_exact_under_backpressure (test.test_agc.TestAGC) ... ok
test_feedback_delay_selection (test.test_agc.TestAGC) ... ok
test_two_sample_feedback_bit_exact_under_backpressure (test.test_agc.TestAGC) ... ok

----------------------------------------------------------------------
Ran 5 tests in 23.110s

OK
```

## Verification registry and policy ratchets {#ver-registry}

A test suite drifts when blocks are added faster than tests. LiteDSP turns its rules into tests
that fail when a rule is broken, so a missing check is a CI failure rather than a review comment.
The verification registry `test/registry.py` holds one row (`VSPEC`) per block of the flow
registry: its golden model, how its latency is checked, its rate, and whether it co-simulates.

| Test | Rule it enforces |
|----------------------------------|----------------------------------------------------------|
| `test_registry_meta.py` | Every registry block has a `VSPEC` row; every row names a real model |
| `test_metadata_policy.py` | Parameters have defaults, approved names, `ValueError` on bad values, latency classified |
| `test_latency.py` | The published `self.latency` matches the measured cycle latency |
| `test_bypass.py` | With `bypass` set, every bypass-capable block is an exact passthrough; the complex FIR is also switched under traffic |
| `test_width_sweep.py` | Representative blocks stay bit-exact at 12, 18 and 24 bits |
| `test_hypothesis.py` | Sampled constructor parameters build, elaborate and match the model |
| `test_style.py` | The LiteX coding style of `tools/check_style.py` |

`test_latency.py` measures the cycle latency under free flow and excludes 99 blocks whose latency
depends on the data, the frame or the rate (transforms, rate changers, composites, serial
engines); most of them check their alignment in their own test. A second class of the same file,
`TestExcludedBlockLatency`, measures the excluded blocks it can drive: the register-exchange
Viterbi decoder, the iterative FFT (first output and frame period), and the DDC, DUC and
channelizer against their bare rate changer.

The property tests need Hypothesis (the `develop` extra) and are skipped without it. Locally they
use the `pr` profile, derandomized, with 8 sampled configurations per block for the elaboration
test; the nightly job selects the `nightly` profile and 100 configurations.

## Verilator lint and co-simulation {#ver-cosim}

The Migen simulator evaluates expressions at full width, while the emitted Verilog sizes an
expression by its context. An inline product assigned to a 16-bit signal is therefore computed on
16 bits in Verilog: the unit tests pass and the gateware is wrong. The co-simulation found this
in the gain block, the window and the FFT stage twiddle path; each holds its product in an
explicitly sized Signal before the rescale.

The lint runs Verilator on the Verilog of every flow-registry block, with every stream endpoint
and every plain control Signal as a port, so that no logic folds away. It waives only the warning
classes that Migen's emitter produces by construction (`WIDTHEXPAND`, `WIDTHTRUNC` and a few
others listed in `sim/verilator.py`); latches, combinational loops, multiple drivers and other
width warnings stay enabled.

The co-simulation compiles one generic C++ testbench (`sim/stream_tb.cpp`) per block, against a
port map generated from the block's stream layouts. It feeds the stimulus of the block's entry in
`sim/cosim_specs.py`, applies seeded random backpressure on both sides, and compares the output
with the golden model. `check_coverage()` fails when a block marked for co-simulation in
`test/registry.py` has no entry; `KNOWN_FAIL` lists the blocks that diverge, and it is empty.

```sh
# Lint every registry block.
python3 sim/run_lint.py
# Co-simulate every table entry, or a selection, with a given backpressure pattern.
python3 sim/run_blocks.py
python3 sim/run_blocks.py agc window --seed 2 --throttle 40 --ready-rate 60
# List the table entries.
python3 sim/run_blocks.py --list
```

The capture below co-simulates the level and analysis blocks of the table, on the default branch
with Verilator 5.025. Each line is one compiled block and its bit-exact comparison; the default
seed is 1, with 25 % input throttling and 75 % output readiness.

```console
$ python3 sim/run_blocks.py gain clipper squelch agc envelope log2 magnitude window \
    psd bit_reverse welch parallel_fft_native_x2
gain               Verilator co-sim:  296 samples, 1 sink(s), 2 field(s), seed=1: PASS
clipper            Verilator co-sim:  296 samples, 1 sink(s), 2 field(s), seed=1: PASS
squelch            Verilator co-sim:  296 samples, 1 sink(s), 2 field(s), seed=1: PASS
agc                Verilator co-sim:  296 samples, 1 sink(s), 2 field(s), seed=1: PASS
envelope           Verilator co-sim:  296 samples, 1 sink(s), 1 field(s), seed=1: PASS
log2               Verilator co-sim:  296 samples, 1 sink(s), 1 field(s), seed=1: PASS
magnitude          Verilator co-sim:  296 samples, 1 sink(s), 1 field(s), seed=1: PASS
window             Verilator co-sim:  188 samples, 1 sink(s), 4 field(s), seed=1: PASS
psd                Verilator co-sim:   64 samples, 1 sink(s), 1 field(s), seed=1: PASS
bit_reverse        Verilator co-sim:   60 samples, 1 sink(s), 4 field(s), seed=1: PASS
welch              Verilator co-sim:   64 samples, 1 sink(s), 1 field(s), seed=1: PASS
parallel_fft_native_x2 Verilator co-sim:   24 samples, 1 sink(s), 4 field(s), seed=1: PASS

12/12 bit-exact
```

Every push runs the whole table once (`sim/run_blocks.py`) together with two dedicated runners,
`sim/run_nco.py` and `sim/run_fir.py`. The nightly run repeats the table with three backpressure
patterns: seed 1 by default, seed 2 at 40 % throttling and 60 % readiness, seed 3 at 10 % and 90 %.

## Coverage {#ver-coverage}

A co-simulation that passes but never reaches part of a block proves little about that part.
`sim/run_coverage.py` reruns every co-simulation entry with Verilator line coverage and reduces
the result to the fraction of covered lines of each block's Verilog. With `--min 90`, used every
night, it fails when a block is below 90 %.

Some generated lines cannot be reached by a valid stimulus: Migen expands selectors and state
machines into case arms that Verilator does not credit. Those blocks are waived in
`sim/coverage_waivers.json`, each with a reason and the named unit tests that check the behaviour
instead. The runner checks that each named test exists, so a waiver cannot point at nothing.

```sh
python3 sim/run_coverage.py nco gain     # Report only, for a selection (all without names).
python3 sim/run_coverage.py --min 90     # The nightly gate.
```

## Formal verification of the stream plumbing {#ver-formal}

The plumbing blocks (buffers, FIFOs, delays, fan-out, muxes, packers) carry little arithmetic but
all the handshake logic of a chain. They are proven with SymbiYosys against the LiteX stream
contract under arbitrary traffic: every input `valid`, payload, `first`, `last` and every output
`ready` is a free input, so the solver explores every producer and consumer timing, not a random
sample of them.

The claim is precise: at the listed configurations, these blocks lose no sample and duplicate no
sample under arbitrary backpressure. `formal/wrapper.py` emits each block to Verilog as the
simulation and implementation flows do, generates a top that binds the checkers of
`formal/stream_props.sv`, and `formal/run_formal.py` runs one SymbiYosys job per block.

### Properties {#ver-formal-props}

Each block is checked from a reset at cycle 0 against four properties.

1. **Stability**: once `valid` is high with `ready` low, `valid` stays high and the payload,
   `first` and `last` stay unchanged on the next cycle. It is assumed on the block's inputs, a
   well-behaved producer, and asserted on its outputs.
2. **Token conservation**: a running difference adds a weight per input transfer and subtracts
   one per output transfer, the weights encoding the block's rate (1:2 for a packer of ratio 2). It
   must stay within proven bounds forever: above the upper bound a sample was lost, below the lower
   bound an output ran ahead of its input, a duplication.
3. **No valid from nowhere**: a block with a registered output keeps `valid` low until its first
   input transfer after reset.
4. **Cover**: the solver must also reach four output transfers, and where possible an output stall
   with `valid` high. An over-constrained setup then fails instead of proving nothing.

Blocks with several endpoints get their own assertions too: each output of `split` sees every
input transfer exactly once, the inputs of `combine` are consumed together, `channel_mux` never drains an unselected
input and `channel_demux` never raises `valid` on an unselected output.

### Results {#ver-formal-results}

The proofs run at `data_width=4`: the properties do not depend on the payload width, and a small
width keeps the solver fast. `prove` is k-induction and holds for unbounded time; `bmc` is a
bounded model check, exhaustive over every input and backpressure pattern of 30 cycles. The
capture below is the full suite on the default branch, with OSS CAD Suite tools on the path.

```console
$ python3 formal/run_formal.py
[formal] smtbmc solver: bitwuzla
skid_buffer    bmc   depth=30 tokens 1:1 diff[+0, +2]      0.8s : PASS
stream_fifo    bmc   depth=30 tokens 1:1 diff[+0, +2]      1.0s : PASS
delay_d1       bmc   depth=30 tokens 1:1 diff[+0, +1]      0.8s : PASS
delay_d2       bmc   depth=30 tokens 1:1 diff[+0, +2]      0.8s : PASS
split          bmc   depth=30 tokens 1:1 diff[-1, +0]      1.0s : PASS
combine        bmc   depth=30 tokens 1:1 diff[+0, +1]      0.9s : PASS
channel_mux    prove depth=30 tokens 1:1 diff[+0, +0]      0.9s : PASS
channel_demux  prove depth=30 tokens 1:1 diff[+0, +0]      0.8s : PASS
cdc            prove depth=30 tokens 1:1 diff[+0, +0]      0.7s : PASS
iq_pack        bmc   depth=30 tokens 1:2 diff[+0, +2]      0.8s : PASS
iq_unpack      bmc   depth=30 tokens 2:1 diff[-1, +0]      0.7s : PASS
downsampler    bmc   depth=30 tokens 1:2 diff[-1, +2]      0.8s : PASS
upsampler      bmc   depth=30 tokens 2:1 diff[+0, +2]      0.8s : PASS

13/13 blocks formally verified (stability + token conservation + cover) in 10.9s
```

The configurations behind each line are small: FIFO and delay depths of 1 or 2, two channels for
`split`, `combine` and the muxes, a ratio or factor of 2 for the packers and rate changers, and a
constant but arbitrary select for the muxes. The `diff` bounds are the proven-tight bounds of the
weighted difference.

The three negative lower bounds come from the architecture, not from duplication. `iq_unpack`
hands out the first sample of a word before it consumes the word, the `downsampler` keeps the
first sample of its group, which can leave before the group's dropped samples arrive, and an
output of `split` can take a sample before the other outputs. Each dip is exactly one sample and
never exceeds it.

The `bmc` blocks use a bounded check because k-induction does not close on them without lemmas
on their internal state, and the checkers see only the ports; for buffers of one or two entries,
30 cycles cover every occupancy many times. `--solver`, `--block` and `--depth` select the
solver, the blocks and the depth.

### Checker validation and scope {#ver-formal-scope}

The checkers were validated by breaking real handshake logic in the emitted Verilog. A `delay`
pipeline that advances while stalled, and a `delay` whose `sink.ready` is stuck high, both fail
token conservation. An undriven or over-constrained setup fails the cover task.

The scope is stated in `doc/formal.md` and is the following.

- Formal owns the plumbing; the co-simulation owns the numbers. The payload values of arithmetic
  blocks are checked bit-exact against the golden models, not proven.
- The proofs cover only the listed small configurations. The handshake code does not change with
  width, depth or channel count, but that is an argument, not a proof.
- `cdc` is proven in its same-domain form only, where the LiteX clock-domain crossing reduces to a
  passthrough; the asynchronous FIFO is a multi-clock problem outside this setup.
- `iq_pack` is proven with `first` and `last` tied low: the LiteX up-converter emits a partial word
  when `last` arrives mid-word, which breaks plain sample accounting.
- Runtime controls are pinned or constant: `factor` at 2, the selects constant. Changing a mux
  select during a stall breaks stability by design and is not claimed.
- `delay`, `combine`, `downsampler` and `upsampler` do not propagate `first` and `last`; their
  source markers are undriven and left out of their stability check.
- `split` is an eager fan-out: an output that takes the sample before the others drops `valid`
  until the input sample is consumed, so it may be one transfer ahead of the input (bound
  `[-1, 0]`). Its per-output counts do not close by induction, so it is checked by a bounded model
  check.

## Quality characterization {#ver-char}

A block can be bit-exact and yet be a poor filter or a noisy oscillator. The characterization
measures datasheet metrics (SFDR, ENOB, image rejection, ripple, attenuation, droop, settling,
IMD3, PAPR reduction, sidelobe level) and gates them against recorded baselines, so a change that
degrades quality fails like a change that breaks a test.

The measurements run on the golden models of `test/models.py`, which keeps them fast and
deterministic; the CORDIC is measured through a Migen simulation of the block.
Because the co-simulation holds the models bit-exact to the Verilog, the numbers describe the
gateware. They are *measured on the golden models*, not on a board.

Each metric of `char/specs.py` has a stimulus, a measurement from `char/metrics.py` and a direction.
The baseline in `char/budgets.json` becomes a gate 3 % of its value away, at least 0.01, in the
direction of a regression: a "min" metric such as SFDR may not fall below it, a "max" metric such
as ripple may not rise above it. The fixed stimuli make the runs repeatable; the tolerance only
absorbs numeric library drift.

```sh
python3 char/run_char.py                    # Measure every block and apply the gate.
python3 char/run_char.py --update --report  # New baseline and report after a deliberate change.
```

The capture below is a full run, trimmed to the level-control metrics; `ok` means within the
gate. The full table and the stimulus of each block are in [Quality
characterization](#perf-quality).

```console
$ python3 char/run_char.py
=== quality characterization: 10 blocks ===
block      metric                         unit   measured  status
[...]
agc        settling_samples            samples     30.000  ok
agc        steady_state_error_pct            %      0.724  ok
agc        overshoot_pct                     %      0.000  ok
clipper    imd3_dbc                        dBc     15.452  ok
cfr        papr_reduction_db                dB      1.567  ok
cfr        evm_below_threshold_pct           %      1.619  ok
[...]
```

## Implementation flows {#ver-impl}

Simulation says nothing about whether a block fits, maps to the right primitives or closes timing.
The implementation flow builds every configuration of `impl/modules.py` with real FPGA tools, out
of context: Yosys and nextpnr for ECP5, Vivado for Artix-7 and Artix UltraScale+. It checks that
the portable, vendor-free Verilog synthesizes on both vendors and that its resources and fmax do
not regress. The devices and tool versions are in [How the implementation numbers are
produced](#perf-conditions).

Each configuration is a factory that returns the block, the ports to expose and the clock period to
constrain. `impl/run.py` emits the Verilog, runs the tools, parses LUT, FF, BRAM and DSP counts and
the routed fmax, and compares them with `impl/budgets.json`. Synthesis and post-route counts are
kept apart, so a synthesis estimate never overwrites a routed result.

| Gate | Rule |
|----------------------------|--------------------------------------------------------------|
| Resources | A count may exceed its baseline by 15 % at most |
| Floor | The routed fmax must stay above `fmax_min`, 85 % of the recorded raw fmax |
| Target | With `--target-gate`, the routed fmax must also meet `fmax_target` |
| Closed targets | With `--closed-target-gate`, only the `TARGET_CLOSED` set must meet its target |

The floor absorbs seed and tool noise; the target is a reviewed engineering objective, 100 MHz for
most configurations. A target that is not yet met is reported but fails a run only with
`--target-gate`, so objectives under development stay advisory while the closed ones are strict.

| Selection | Content |
|---------------------------|---------------------------------------------------------------------|
| All | Every configuration, synthesis |
| `--subset` | `PNR_SUBSET`: representative configurations for place and route |
| `--stability` | `PNR_STABILITY`: route-sensitive closed targets, median of three routes |
| `--stress` | `PNR_STRESS`: wide configurations near the device capacity |
| `--target-closed` | `TARGET_CLOSED`: the reviewed set with strict targets |

```sh
# All blocks, Yosys synthesis for ECP5 (fast).
python3 impl/run.py --device ecp5 --flow synth
# Place and route of the subset, gated on floors and closed targets.
python3 impl/run.py --device ecp5 --flow pnr --subset --closed-target-gate
# Three routes of the route-sensitive configurations, gated on their medians.
python3 impl/run.py --device ecp5 --flow pnr --stability --repeat 3 --target-gate
# One configuration on Artix-7, with the three Vivado strategies.
python3 impl/run.py --device xilinx --flow pnr --module fft_parallel_native_x2 --strategies all
# Refresh the baseline after a deliberate change.
python3 impl/run.py --device ecp5 --flow synth --update-budgets
```

`--seeds` or `--repeat` runs several nextpnr routes of one synthesis, and `--strategies all` three
Vivado strategies; the result reports the worst, median and best fmax, and a budget update records
the median.

Two configurations are complete generated cores, `ddc_ip` and `qpsk_receiver_ip`: the datapath,
the AXI-Stream ports, the AXI-Lite to CSR bridge and every register bank, routed together. They
check the integration path that [Flow, generator, GUI and host software](#tooling) describes. Every
week the Xilinx workflow also packages the DDC and QPSK examples as IP-XACT cores, instantiates
them in a Vivado IP Integrator block design and synthesizes the wrappers on both device families.

### What the flows found {#ver-findings}

The implementation runs caught problems that no simulation shows. Each finding below led to a
change in the block and to a rule for new blocks.

| Block | Finding | Rule |
|--------------------|-----------------------------------------------------------------|----------------------------------|
| Iterative FFT | Asynchronous-read RAM with four ports spilled to LUTs, no BRAM | Large RAMs: synchronous read, two ports |
| Quarter-wave NCO | At `lut_depth=1024` its table maps to LUTs | Prefer the full LUT at small depths |
| LMS equalizer | Weights wider than their range used several DSPs per product | Size operands to their value range |
| RMS | An unrolled square root for one result per window | Match unrolling to throughput |
| Farrow, window | Long feed-forward paths | Register them: latency only |
| Runtime FIR in the DDC IP | Vivado flattened a 33-tap sum into a 68-level DSP cascade | Pipeline the reduction tree explicitly |
| AGC, CIC, FFT, Viterbi | Loop paths that a register cannot cut | An explicit architecture option |

The last rule is the subject of [Timing architecture](#perf-timing-arch): a feed-forward block
takes extra registers as extra latency, while a recursive block needs an architecture that keeps
its numerical recurrence, with its own model and tests. The classic architectures are the API
defaults, except the CCSDS Reed-Solomon decoder, which defaults to its pipelined architecture.

## Continuous integration map {#ver-ci}

| Workflow | Trigger | What it runs |
|----------------------------|--------------------|----------------------------------------------------------|
| `ci.yml` | Push, pull request | Unit tests in 4 shards on Python 3.9 and 3.11; examples with plotting; Verilator lint and co-simulation; style and generated-document checks; package build and wheel test |
| `impl.yml` | Push, pull request | ECP5 synthesis of every block, without the budget gate; place and route of the subset; three-route stability set |
| `bench.yml` | Push, pull request | Elaboration of the bench SoCs |
| `nightly.yml` | Every night | Full suite with several seeds; co-simulation with three backpressure patterns; coverage at 90 %; characterization gate; Hypothesis nightly profile; formal suite; ECP5 synthesis with budget gate, place and route subset, stability and stress routes |
| `impl-xilinx.yml` | Weekly; manual | Artix-7 and Artix UltraScale+. Weekly: IP packaging and block-design synthesis. Manual: synthesis of every block, strict closed targets, strategy sweeps |

The generated-document checks of every push are `python3 -m litedsp.flow.docgen --check` (block
datasheets), `python3 impl/report.py --check` (`doc/resources.md`) and
`python3 char/run_char.py --check-report` (`doc/characterization.md`). The Xilinx workflow runs on
a self-hosted runner labelled `vivado`; the ECP5 jobs use a pinned OSS CAD Suite release.

## Verifying a new block {#ver-new-block}

Beyond the golden model, the test and the registry rows of the checklist of [Adding a
block](#arch-new-block), a new block joins the verification flows in three places:

1. a co-simulation entry in `sim/cosim_specs.py` when its `VSPEC` row asks for one;
   `check_coverage()` enforces it;
2. optionally, a characterization spec in `char/specs.py` and its baseline, for a block with a
   quality metric;
3. a factory in `impl/modules.py` and its results in `impl/budgets.json`, from `impl/run.py
   --update-budgets`, then `python3 impl/report.py` and `python3 doc/manual/performance.py`.

Next: [Debugging](#debugging) for the method on a failing chain, and
[Performance and resources](#performance) for the recorded numbers.
