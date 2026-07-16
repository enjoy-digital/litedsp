# Timing architecture decisions

The implementation manifest keeps two independent timing values: `fmax_min` is the
noise-tolerant regression floor, while `fmax_target` is the engineering objective. Feed-forward
paths may reach a target through latency-only retiming. The families below contain a
sample-to-sample or schedule feedback loop, so inserting a register changes throughput, state
evolution, or both. Each therefore lands as a separately reviewed architecture option rather
than an invisible change to the existing block.

The common objective for the configurations below is 100 MHz on the reference ECP5-85 device.
Current values are the checked-in raw P&R measurements, not the 85% regression floors.

| Family/configuration | Current ECP5 | Recurrence that limits timing | First implementation to evaluate |
|---|---:|---|---|
| Viterbi hard / soft | 47.4 / 46.5 MHz classic; 106.0 / 110.8 MHz folded | ACS metric update followed by the global-min tree and normalization | folded option landed and target-closed |
| AGC | 49.6 MHz classic; 106.3 MHz delayed | gain multiply, output magnitude, error and gain integration in one accepted-sample step | delayed option landed and target-closed |
| CIC decimator / interpolator | 80.0 / 69.7 MHz classic; 364.4 / 243.5 MHz staged | cascaded integrator/comb arithmetic must update coherent state | staged option landed and target-closed |
| CIC parallel x2 / x4 | 279.5 / 204.2 MHz staged | vector integrators use registered logarithmic-depth lane-prefix scans | both options landed and target-closed |
| SDF / iterative / parallel-x2 FFT | 58.7 / 73.6 / 56.9 MHz classic; 102.7 folded SDF; 107.6 registered iterative | butterfly result feeds the SDF delay or in-place RAM schedule | folded SDF and iterative target-closed; interleaved/parallel remain open |

## Viterbi decoder

The current K=7 decoder updates all 64 state metrics and 64 register-exchange survivor paths
every symbol. Its feedback path is predecessor metric + branch metric, ACS, a six-level global
minimum, then subtraction back into every metric. A register inside that chain would make the
next symbol use stale metrics and is not a latency-only change.

The first variant replaces register-exchange survivors with decision RAM and periodic
traceback, then normalizes metrics every configurable `normalize_interval` symbols instead of
every symbol. Wider metrics absorb the bounded growth between normalizations, while two
registered three-level reductions find the best of the 64 states outside the ACS recurrence.

The option is now implemented as `decision_memory=True`. At the default K=7 / traceback=56,
the synchronous RAM traceback takes 110 clocks and nominal `cycles_per_output` is 114, plus one
normalization clock every 16 accepted symbols. The sink is stalled during best-state reduction,
normalization, traceback, and output backpressure; the architecture therefore prioritizes area
and clock rate over coded-symbol throughput. Hard and soft outputs remain bit-exact against the
same golden model.

On ECP5, the hard/soft configurations reach 106.0/110.8 MHz with 6634/6848 LUT, 864 FF, and two
BRAMs, versus 47.4/46.5 MHz and 11053/11942 LUT, 3945 FF, and no BRAM for register exchange. On
Artix-7 they reach 106.6/105.4 MHz with 4171/3440 LUT, 802 FF, and one BRAM. Both device families
are target-closed at 100 MHz; register exchange remains the compatibility default.

Trade-offs:

- Decision RAM removes most of the roughly 3.9k survivor FFs and their high-fanout routing, but
  decoded output arrives only after a folded traceback rather than directly from an exchange
  register.
- Less-frequent normalization removes the global-min tree from the per-symbol feedback path at
  the cost of wider metric adders and a proof that the selected interval cannot overflow.
- A folded 32-ACS implementation remains a lower-area fallback: it
  uses two clocks per symbol and roughly halves ACS logic. It is not the default because it
  reduces coded-symbol throughput.
- A deeply pipelined one-symbol-per-clock design requires two or more independent metric
  contexts (interleaved framed codewords); state memory and control scale with the context count.

Acceptance requires hard and soft bit identity, tie behavior, punctured-zero LLR handling, and
the existing BER/waterfall bounds. The option publishes traceback and output-cycle counts; its
stream handshake makes the required input gap explicit while traceback is active.

## AGC

The current loop applies `gain[n]`, derives `|y[n]|`, and commits `gain[n+1]` on the same
accepted transfer. The multiply/rescale, magnitude approximation, error calculation and clamp
therefore form one feedback path.

The preferred option updates gain from the already-registered output magnitude on the following
accepted sample. Sample throughput and datapath latency stay at one per clock and one clock,
respectively, but the control loop gains one unit delay. This must be a parameterized architecture
because it changes the exact gain trajectory even though the steady-state target is unchanged.

The option is now implemented as `delayed_feedback=True`.  A pending observation register keeps
the sample-domain trajectory invariant when an output drains during an input gap.  The registry
configuration reaches 106.3 MHz on ECP5 and 103.3 MHz on Artix-7, compared with 49.6 MHz for the
classic ECP5 loop; ECP5 resources change from 642 LUT / 57 FF / 8 DSP to 349 LUT / 75 FF / 4 DSP.
Characterization settles in 31 samples with 0.733% residual error and no measured overshoot for
the reviewed stimulus.

Trade-offs:

- One delayed observation is the smallest area change and cleanly separates the multiplier from
  loop integration; settling time and overshoot must be re-characterized for each `mu`.
- Updating gain every 2 or 4 samples further relaxes timing and switching power, but lengthens
  acquisition approximately in proportion to the update interval.
- A look-ahead predictor can preserve the old trajectory more closely, but duplicates arithmetic
  in the feedback path and defeats the timing/area objective.

Acceptance requires a bit-exact model for the selected delayed loop, randomized backpressure,
clamp/IRQ behavior, and characterization gates for settling samples, residual error and
overshoot. The current immediate-loop architecture remains available for compatibility.

## CIC family

The serial CIC computes each integrator's new value from the preceding stage's new value in one
cycle; the output-rate combs are similarly cascaded. The x4 implementation expands the same
recurrence across four samples with a lane-prefix network. Registering an arbitrary adder changes
which sample phase reaches the rate-change boundary.

The serial option should register every integrator and comb boundary, explicitly account for the
resulting group delay, and align the decimation strobe/output phase to the existing mathematical
sequence. Hogenauer wrap-around widths and gain normalization do not change. For x4, first test a
two-level prefix pipeline; if routing remains dominant, expose a two-lane option instead of
forcing four samples per clock.

The serial staged option is now implemented as an elastic pipeline.  Each accepted sample carries
its decimation phase through one-adder integrator stages; marked samples then traverse one-
subtractor comb stages.  The interpolator uses the reverse ordering around an explicit zero-stuff
phase generator.  For the N=4 implementation configuration this raises ECP5 timing from
80.0/69.7 MHz to 364.4/243.5 MHz (decimator/interpolator), changes latency from 1 to 8 clocks, and
keeps one-sample-per-clock peak throughput.  The compatibility architecture remains the default;
the implementation and co-simulation registries select `staged=True`.

Trade-offs:

- Fully staged serial CIC remains one input sample per clock but adds about `N-1` clocks of group
  delay and `N*W` pipeline state per I/Q path.
- Pipelining the x4 prefix keeps four-sample throughput but adds lane-history registers and a
  fixed beat of latency; two lanes approximately halve the prefix width and peak throughput.
- Time-multiplexing a single adder minimizes area but needs `N` clocks per accepted sample and is
  only suitable when the fabric clock is well above the sample rate.

Acceptance requires bit identity after the declared delay/phase adjustment, impulse and random
wrap-around vectors, runtime backpressure, and unchanged CIC droop characterization.

The parallel option is now implemented with the same elastic stage boundaries, but each stage
processes a complete vector using an inclusive Kogge-Stone lane scan. The x4 scan has two adder
levels plus the stage accumulator rather than the old 16-adder beat recurrence. Both choices keep
one beat per clock and add eight clocks of latency for N=4:

| Parallel CIC | Peak input | ECP5 LUT/FF/Fmax | Artix-7 LUT/FF/Fmax |
|---|---:|---:|---:|
| x2 staged | 2 samples/clock | 1113 / 832 / 279.5 MHz | 675 / 834 / 274.8 MHz |
| x4 staged | 4 samples/clock | 2770 / 1167 / 204.2 MHz | 1670 / 1169 / 188.8 MHz |
| x4 classic | 4 samples/clock | 1393 / 482 / 55.6 MHz | 1219 / 482 / not routed |

Thus x2 is the lower-area choice when two samples/clock suffice; x4 retains the original aggregate
throughput for roughly 2.5x/2.0x the x2 ECP5 LUT/FF cost. The classic architecture remains the API
default, while both staged registry configurations are strict 100 MHz timing sentinels.

## FFT family

In an SDF stage the butterfly difference is twiddle-multiplied, scaled and written into the delay
feedback on the same beat. The iterative core has an equivalent read/butterfly/write schedule in
BRAM. A register in either feedback edge changes which operands meet unless the schedule or the
number of independent contexts also changes.

Two explicit SDF options are implemented:

1. A folded SDF stage splits butterfly/twiddle work over two clocks. Timing improves, but
   throughput becomes one sample every two clocks and the stage-state registers substantially
   increase FF use.
2. An interleaved stage pipelines the butterfly and alternates two independent frames/channels.
   Aggregate throughput returns to one sample per clock, at the cost of duplicated delay state,
   stricter framing, and roughly doubled storage.

At N=256 the folded serial core is bit-identical to scaled classic mode and reaches 102.7 MHz on
ECP5 and 119.1 MHz on Artix-7, versus 58.7 MHz for ECP5 classic. It uses 4243 LUT / 2118 FF / 28
DSP on ECP5 and sustains 0.5 sample/clock. Two alternating folded contexts restore aggregate
one-sample/clock throughput; they reach 95.2 MHz on ECP5 and 117.4 MHz on Artix-7 at roughly
twice the state and multiplier cost. The framing contract deliberately requires two independent
interleaved frames/channels rather than pretending this is a latency-only classic replacement.

The x2 parallel FFT inherits the SDF choice in both sub-cores. Folded mode reduces average
throughput from two to one sample/clock and raises Artix-7 timing from 81.0 to 94.6 MHz, with
5312 LUT / 3354 FF / 104 DSP post-route. The current ECP5 netlist synthesizes to 9253 LUT / 4386
FF / 56 DSP but does not complete nextpnr placement at this utilization, even with a 70 MHz
constraint; it is therefore excluded from the nightly P&R subset and carries no stale ECP5 fmax.

The iterative option is now implemented as `registered_butterfly=True`: the read phase registers
the asynchronous twiddle ROM result, and a fourth butterfly phase registers the scaled sums and
differences before BRAM writeback.  At N=256, `cycles_per_frame` rises from 3584 to 4608 (+28.6%),
ECP5 resources move from 995 LUT / 91 FF / 2 BRAM / 4 DSP to 1013 / 187 / 2 / 4, and timing rises
from 73.6 to 107.6 MHz.  Artix-7 closes at 104.5 MHz with 295 pre-opt synthesis LUTs (254
post-route), 90 FF, 1 BRAM, and 5 DSP.  The
default three-cycle butterfly remains available; the implementation registry selects the
registered option.

Acceptance requires bit identity versus `fft_fixed_model` for scaled mode, the existing BFP
exponent/overflow contract, forward/inverse operation, exact frame markers under backpressure,
and published latency, frame gap, samples/clock, LUT/FF/BRAM/DSP and achieved fmax.

## Landing policy

Each family is a separate change series: architecture parameter and model first, focused tests
second, then ECP5 and Artix-7 implementation results. A new option may become the default only
when its stream contract and numerical behavior are documented and downstream composites have
been re-verified. Raw measurements refresh `fmax_mhz`/`fmax_min`; the 100 MHz target remains
manually reviewed and is checked explicitly with `impl/run.py --target-gate`.
