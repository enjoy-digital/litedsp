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
| AGC | 49.6 MHz classic; 133.9 MHz two-sample pipeline | gain multiply, output magnitude, error and gain integration in one accepted-sample step | two-sample option landed and target-closed |
| CIC decimator / interpolator | 80.0 / 69.7 MHz classic; 364.4 / 243.5 MHz staged | cascaded integrator/comb arithmetic must update coherent state | staged option landed and target-closed |
| CIC parallel x2 / x4 | 279.5 / 204.2 MHz staged | vector integrators use registered logarithmic-depth lane-prefix scans | both options landed and target-closed |
| DUC FIR interpolator | 74.3 MHz classic; 107.1 MHz pipelined | asynchronous coefficient selection, multiply, and serial accumulator feedback | product-register option landed and target-closed |
| Resampler farm | 86.3 MHz classic; 152.8 MHz pipelined median | channel-banked distributed-RAM lookup, multiply, and serial accumulator feedback | operand/product pipeline landed and target-closed |
| Frame synchronizer (Barker-7) | 79.9 MHz classic; 132.2 MHz pipelined median | matched-filter reduction, input-power/energy update, and normalized-threshold product | five-stage latency-only retiming landed and target-closed |
| RS decoder (255,223) | 86.5 MHz classic; 124.3 MHz pipelined median | serial GF multipliers, inverse/Forney chain, and Chien reductions | scheduled operand/reduction pipeline landed and target-closed |
| LMS equalizer (7 taps) | 69.1 MHz classic; 114.0 MHz all-mode pipelined median | FIR rescale, CMA modulus/gradient, and saturated weight recurrence | nine-sample delayed-update option landed and target-closed |
| SDF / iterative / parallel FFT | 58.7 / 73.6 / 56.9 MHz classic; 113.6 folded SDF; 110.5 interleaved x2; 107.6 registered iterative; 122.8/98.4 pipelined native P2/P4 | butterfly result feeds the SDF delay or in-place RAM schedule; vector cascade also propagates ready | folded, interleaved, iterative, and native P2 target-closed; native P4 remains open on ECP5 |
| PFB channel transform (M=16/T=8) | 113.2 MHz FFT | polyphase accumulator and FFT memory-read/multiply/write schedule | four-phase FFT option landed and target-closed |

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

## Half-band structural zero pruning

Half-band wrappers now compact their serial-MAC schedules around the exact-zero coefficients
created at build time. For the default 23-tap decimator this reduces the scheduled products from
23 to 13 and the complete output interval from 26 to 16 clocks. The corresponding interpolator
uses phase schedules of 12 and one products and completes both phase outputs in 15 clocks rather
than 26. Coefficient storage is compacted with the schedule; omitted structural zeros are
intentionally not runtime-writable.

The constant history-index lookup makes the individual ECP5 clock slower than the old rectangular
counter: three routes reach 109.2/112.8/112.8 MHz instead of the previous 146.4 MHz baseline.
Aggregate decimator capacity nevertheless rises from 5.63 to 7.05 million outputs/s because each
window takes ten fewer clocks. Artix-7 reaches 146.8 MHz and Artix UltraScale+ 327.7 MHz. The
default decimator uses 453 LUT / 157 FF / 2 DSP on ECP5, 231 / 94 / 2 on Artix-7, and 225 / 94 / 2
on Artix UltraScale+. Bit-exact randomized-stall tests cover both directions against the complete
unpruned mathematical model.

## DUC FIR interpolator

The FIR-based DUC uses two serial MACs, one per I/Q component, for each polyphase output. In the
classic schedule an asynchronous coefficient lookup, multiplier, and accumulator update share a
clock. The pipelined option replaces the phase/tap address expression with a sequential
coefficient pointer, registers each product, and consumes the final product in a drain clock.

For the implementation configuration (L=8, 65 taps), `cycles_per_output` rises from 11 to 12 and
nominal FIR latency from 65 to 66 clocks; the numerical output and output rate remain unchanged.
ECP5 moves from 74.3 MHz, 643 LUT / 302 FF / 7 DSP to 107.1 MHz, 763 LUT / 374 FF / 6 DSP.
Artix-7 reaches 120.5 MHz with 381 LUT / 142 FF / 1 BRAM / 6 DSP post-route, and Artix
UltraScale+ reaches 255.2 MHz with 373 LUT / 142 FF / 1 BRAM / 6 DSP. The classic architecture
remains the API default; the implementation registry selects the pipelined option.

Acceptance covers odd and even branch lengths, exact fixed-point output, randomized input/output
stalls, the DUC image-rejection/upconversion test, and an independent Verilator co-simulation.

## Resampler farm

The farm time-shares one complex serial MAC across four rate-locked channels. Its classic path
reads the channel-major sample history from distributed RAM, multiplies by the selected tap, and
updates the accumulator in one clock. The pipelined option registers the RAM operands and the
product, then drains those two stages after the last tap. This makes the implementation schedule
`R + n_taps + 4` rather than `R + n_taps + 2` clocks per output; it does not change channel order,
decimation, or arithmetic.

At four channels, R=8, and 32 taps, three ECP5 routes reach 151.6/152.8/157.5 MHz. Registering the
read boundary also enables two ECP5 BRAMs for the banked histories: post-route resources move
from 920 LUT / 106 FF / 0 BRAM / 2 DSP to 550 / 189 / 2 / 2. Artix-7 reaches 182.5 MHz with
558 LUT / 109 FF / 2 DSP and Artix UltraScale+ reaches 347.6 MHz with 535 / 109 / 2. The classic
architecture remains the API default; the implementation registry selects the pipelined option.

Acceptance covers two, three, and four channels, multiple tap/rate combinations, exact per-channel
models under independent input stalls and output backpressure, channel isolation, and composition
with `LiteDSPChannelDemux`.

An optional channel-major coefficient memory now gives each stream an independent response while
retaining the single complex MAC. With four 32-tap banks, ECP5 uses 554 LUT / 214 FF / 3 BRAM /
2 DSP and routes at 131.8/132.7/133.7 MHz. Artix-7 uses 599 / 109 / 0 / 2 at a 171.5 MHz median;
Artix UltraScale+ uses 574 / 109 / 0 / 2 at 385.1 MHz. The shared-ROM configuration remains the
default and avoids the extra ECP5 coefficient BRAM. Verification independently initializes every
bank and reloads a selected bank at runtime, checking that all other channel responses remain
unchanged.

## Frame synchronizer

The normalized detector contains three independent feed-forward timing paths: the matched-filter
sum, raw I/Q power into the moving-energy recurrence, and `threshold * (N * energy)`. The
pipelined option registers every balanced FIR reduction level, registers raw power and aligned
correlation before updating energy, and splits the normalized threshold into `N * energy` then
threshold-product stages. All registers share the sample-qualified advance, so arbitrary bubbles
and backpressure cannot move a peak or frame marker.

For Barker-7, the option adds five samples of latency (`ceil(log2(7)) + 2`) while retaining one
accepted sample per clock. Three ECP5 routes reach 130.6/132.2/132.7 MHz with 990 LUT / 2034 FF /
23 DSP, versus 79.9 MHz and 1519 / 1364 / 23 for classic. Artix-7 reaches 147.5 MHz with
376 LUT / 572 FF / 26 DSP; Artix UltraScale+ reaches 287.9 MHz with 371 / 572 / 26. The three
additional Xilinx DSPs per I/Q matched filter are the published cost of preventing Vivado from
flattening the runtime-coefficient reduction into a DSP48 cascade. Classic remains the API default.

Acceptance covers exact threshold-edge behavior, gain invariance, complex and real preambles,
peak-window/offset alignment, first/last framing, IRQ/count behavior, randomized backpressure,
and independent Verilator co-simulation of the pipelined option.

## Reed-Solomon decoder

The serial RS decoder originally combined GF multiplication, polynomial selection, reductions,
and the shared inverse/Forney path within individual Berlekamp-Massey, Omega, and Chien clocks.
The pipelined schedule registers each multiplier's operands, drains serial recurrences explicitly,
splits the Chien reductions, and registers the inverse operands and final magnitude. It does not
change the conventional-basis GF(256) algorithm, correction result, framing, or status counters.

For RS(255,223), the published worst-case block schedule rises from 2249 to 3126 clocks (+877,
39.0%). Three ECP5 routes reach 122.4/124.3/126.7 MHz with 3780 LUT / 1466 FF / 1 BRAM, versus
86.5 MHz with 3740 / 1321 / 1 for classic. Artix-7 reaches 143.5 MHz with 1632 LUT / 1466 FF;
Artix UltraScale+ reaches 270.1 MHz with 1650 LUT / 1474 FF. All three use zero DSPs. The classic
architecture remains the API default; the implementation registry selects the pipelined schedule.

Acceptance covers clean, correctable, and uncorrectable blocks at t=1, t=2, and the full t=16;
byte-exact model agreement, status/counter behavior, framing under backpressure, and an independent
Verilator co-simulation of the pipelined option.

## LMS equalizer

Preserving the runtime trained/CMA/DD controls exposed three independent paths that a trained-only
implementation had optimized away: FIR rescale into the modulus squares, square-product addition,
and modulus subtract into the CMA multiplier/saturation chain. The pipelined architecture now
registers the scaled output, square products, modulus sum, modulus error, CMA products, and selected
error separately. The explicit `update_pipeline=True` option additionally registers completed
increments at their bounded post-shift width before the weight recurrence. Together they change
delayed-LMS adaptation from one sample in the classic loop to nine accepted samples, while
preserving output latency (three clocks), exact arithmetic, and one-sample-per-clock throughput.

Three ECP5 routes reach 112.3/114.0/116.0 MHz with 5179 LUT / 5397 FF / 60 DSP. Artix-7 reaches
120.3 MHz with 2184 LUT / 4404 FF / 63 DSP, and Artix UltraScale+ reaches 228.7 MHz with 2190 /
4386 / 63. The substantial register cost is deliberate: every pending error carries its tap-window
snapshot, so increasing the loop delay preserves bubble-invariant sample semantics. Trained, CMA,
decision-directed, freeze, queue-collision, and convergence trajectories remain bit-exact against
the nine-sample model. Independent Verilator co-simulation covers runtime mode switching and also
guards full-width modulus/gradient products against generated-Verilog context truncation.

The eight-sample pipelined loop without the recurrence cut and the one-sample classic loop remain
API-compatible choices. The implementation registry selects the nine-sample target-closed option.

## AGC

The current loop applies `gain[n]`, derives `|y[n]|`, and commits `gain[n+1]` on the same
accepted transfer. The multiply/rescale, magnitude approximation, error calculation and clamp
therefore form one feedback path.

The first option updates gain from the already-registered output magnitude on the following
accepted sample. Sample throughput and datapath latency stay at one per clock and one clock,
respectively, but the control loop gains one unit delay. The pinned OSS-CAD toolchain routes this
option at only a 91.4 MHz median, so the implementation configuration uses a second boundary:
register alpha-max-beta-min's max/min components, then form the magnitude on the gain side. This
adds one more accepted-sample control-loop delay without changing datapath latency or throughput.
Both must be explicit architectures because they change the exact gain trajectory even though
the steady-state target is unchanged.

The compatibility option remains `delayed_feedback=True` (one sample); the implementation
registry selects `feedback_delay=2`. A two-entry observation queue keeps the sample-domain
trajectory invariant when an output drains during an input gap. The two-sample configuration
reaches a 133.9 MHz three-seed median on ECP5, 134.9 MHz on Artix-7, and 290.1 MHz on Artix
UltraScale+, compared with 49.6 MHz for the classic ECP5 loop. Post-route resources are 390 LUT /
126 FF / 4 DSP on ECP5, 231 / 126 / 2 on Artix-7, and 203 / 122 / 2 on UltraScale+. Characterization
settles in 30 samples with 0.724% residual error and no measured overshoot for the reviewed
stimulus.

Trade-offs:

- One delayed observation is the smallest area change and separates the multiplier from loop
  integration, but does not close the pinned ECP5 target. Registering max/min for a two-sample
  loop adds 51 ECP5 FFs over that option and provides robust timing margin.
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

1. A folded SDF stage pipelines capture, twiddle multiplication, and feedback completion over
   three edges while overlapping completion with the next capture. Timing improves, but
   throughput remains one sample every two clocks and the stage-state registers substantially
   increase FF use.
2. An interleaved stage pipelines the butterfly and alternates two independent frames/channels.
   Aggregate throughput returns to one sample per clock, at the cost of duplicated delay state,
   stricter framing, and roughly doubled storage.

At N=256 the folded serial core is bit-identical to scaled classic mode and reaches a
105.5/113.6/117.3 MHz worst/median/best ECP5 route sweep and 110.9 MHz on Artix-7, versus
58.7 MHz for ECP5 classic. It uses 4936 LUT / 2674 FF / 28 DSP on ECP5 and sustains
0.5 sample/clock. Registering the butterfly difference and four real twiddle products removes
the multiplier/add chain from the feedback edge. Completion overlaps the next capture, with a
same-address bypass preserving the depth-one recurrence. This adds one clock per FFT rank
(518 clocks total latency at N=256) without changing the two-clock initiation interval or
arithmetic. Artix-7 maps the two largest twiddle tables to BRAM and uses 1726 LUT / 1251 FF /
2 BRAM / 28 DSP post-route.

Two alternating folded contexts restore aggregate one-sample/clock throughput at roughly twice
the state and multiplier cost. The N=256 ECP5 build now reaches 107.5/110.5/115.8 MHz across
three routes with 9898 LUT / 5350 FF / 56 DSP; Artix-7 reaches 112.8 MHz with 3435 LUT / 2504 FF /
2 BRAM / 56 DSP. Both devices therefore close the 100 MHz objective. The framing contract
deliberately requires two independent interleaved frames/channels rather than pretending this
is a latency-only classic replacement.

The x2 parallel FFT inherits the SDF choice in both sub-cores. Folded mode reduces average
throughput from two to one sample/clock and raises Artix-7 timing from 81.0 to 94.6 MHz, with
5312 LUT / 3354 FF / 104 DSP post-route. The current ECP5 netlist synthesizes to 9253 LUT / 4386
FF / 56 DSP but does not complete nextpnr placement at this utilization, even with a 70 MHz
constraint; it is therefore excluded from the nightly P&R subset and carries no stale ECP5 fmax.

The native vector-SDF implementation advances one shared feedback line by P consecutive samples
per clock and removes the split architecture's branch FIFOs, serializers and duplicated cores.
Its `feedback_pipeline=True` option captures signed butterfly differences, registers only the
product bits that can affect exact round-half-up/saturation, and completes feedback on the
following edge. A packed same-address RAM bypass supplies the newest value when a shallow
feedback line is revisited before the registered write becomes visible.

After the arithmetic path was split, ECP5 timing reports exposed the independent elastic-control
limiter: `ready` propagated through every FFT rank into distributed-RAM write enables. A
transparent ready-only skid boundary at the middle of the cascade splits that path in half. It
adds one P-wide beat of storage that is used only on a downstream stall; nominal latency,
arithmetic, and P-sample-per-clock throughput are unchanged. Every serial fixed-point rounding
boundary is retained and randomized backpressure remains bit exact:

| Native FFT (N=256, pipelined) | Latency | ECP5 LUT/FF/DSP/Fmax | Artix-7 LUT/FF/DSP/Fmax | Artix UltraScale+ LUT/FF/DSP/Fmax |
|---|---:|---:|---:|---:|
| P=2 | 144 clocks | 9835 / 5287 / 52 / 122.8 MHz | 2947 / 2954 / 52 / 111.4 MHz | 2865 / 2954 / 52 / 193.5 MHz |
| P=4 | 79 clocks | 16018 / 8978 / 94 / 98.4 MHz | 4898 / 5087 / 95 / 110.5 MHz | 4819 / 5084 / 95 / 180.6 MHz |

Three ECP5 routes of P=2 reach 120.7/122.8/123.7 MHz worst/median/best. Dedicated three-strategy
Vivado sweeps reach 111.4/111.4/111.6 MHz on Artix-7 and 191.9/193.5/193.5 MHz on Artix
UltraScale+. P=2 therefore joins the regular `PNR_SUBSET` and strict `TARGET_CLOSED` set.

P=4 closes both Xilinx profiles, but its ECP5 routes span 85.0/98.4/100.7 MHz. It remains an
isolated `PNR_STRESS` configuration with an advisory 100 MHz objective; the 83.7 MHz regression
floor is deliberately distinct from that target. This is route sensitivity at the larger
94-DSP topology, not a throughput compromise: P=4 still accepts four samples every clock.

The compatibility architecture remains available with `feedback_pipeline=False`. Relative to
its 63.0 MHz ECP5 and 82.4 MHz Artix-7 P=2 results, the target-closed option costs seven clocks,
273 ECP5 FFs over the previous pipelined baseline, and one stall-only skid beat. Relative to the
classic P=4 option, the pipelined result adds six clocks and remains open only on ECP5. The
published post-route counts include the skid storage and the extra commutated-rank state.

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

## PFB channel transform

The direct PFB channelizer time-shares one DFT multiply/accumulate over all M² branch/bin pairs.
That is compact for M<=8, but a folded M=16/T=8 frame would take 816 clocks. The scalable
`architecture="fft"` option retains the same full-precision polyphase FIR, then runs a radix-2
DIF transform with explicit per-rank twiddle rounding and natural-order output.

The timing path is split into the proven two-cycle polyphase MAC plus four FFT phases: register
the dual-memory read/difference, register the twiddle products, write the sum, and write the
difference. A single-write distributed-memory state keeps M=16/T=8 to 2477 LUT / 583 FF / 14 DSP
on ECP5 and 1019 LUT / 346 FF / 10 DSP on Artix-7. Three ECP5 routes reach
110.5/113.2/114.4 MHz; Artix-7 reaches 120.1 MHz. The frame takes 432 clocks—1.9x shorter than
the folded direct schedule—and the advantage grows as O(M log M) versus O(M²).

The FFT arithmetic intentionally has its own bit-exact model: each non-trivial twiddle product
rounds back to the branch accumulator scale after a rank, whereas the small direct DFT rounds
only once after its full sum. Acceptance covers M=16 and M=32, natural channel order, framing,
randomized stalls, Verilator co-simulation, and both FPGA implementation targets.

## Landing policy

Each family is a separate change series: architecture parameter and model first, focused tests
second, then ECP5, Artix-7, and Artix UltraScale+ implementation results. A new option may become the default only
when its stream contract and numerical behavior are documented and downstream composites have
been re-verified. Raw measurements refresh `fmax_mhz`/`fmax_min`; the 100 MHz target remains
manually reviewed and is checked explicitly with `impl/run.py --target-gate`.
