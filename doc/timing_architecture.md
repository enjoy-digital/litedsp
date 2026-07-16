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
| Viterbi hard / soft | 47.4 / 46.5 MHz | ACS metric update followed by the global-min tree and normalization | traceback RAM plus less-frequent normalization |
| AGC | 49.6 MHz | gain multiply, output magnitude, error and gain integration in one accepted-sample step | one-sample-delayed adaptation loop |
| CIC decimator / interpolator | 80.0 / 69.7 MHz | cascaded integrator/comb arithmetic must update coherent state | registered stage cascade with explicit sample-phase alignment |
| CIC parallel x4 | 55.6 MHz | four-lane prefix recurrence expands each serial integrator update | lane-prefix pipeline or fewer lanes per clock |
| SDF / iterative / parallel-x2 FFT | 58.7 / 73.6 / 56.9 MHz | butterfly result feeds the SDF delay or in-place RAM schedule | folded/interleaved butterfly options |

## Viterbi decoder

The current K=7 decoder updates all 64 state metrics and 64 register-exchange survivor paths
every symbol. Its feedback path is predecessor metric + branch metric, ACS, a six-level global
minimum, then subtraction back into every metric. A register inside that chain would make the
next symbol use stale metrics and is not a latency-only change.

The first variant should replace register-exchange survivors with decision RAM and periodic
traceback, then normalize metrics every configurable `normalize_interval` symbols instead of
every symbol. Per-state ACS remains one symbol per clock; wider metrics absorb the bounded
growth between normalizations, and a pipelined best-state reduction can run beside the ACS.

Trade-offs:

- Decision RAM removes most of the roughly 3.9k survivor FFs and their high-fanout routing, but
  decoded output arrives in traceback bursts rather than directly from an exchange register.
- Less-frequent normalization removes the global-min tree from the per-symbol feedback path at
  the cost of wider metric adders and a proof that the selected interval cannot overflow.
- If that is still insufficient, a folded 32-ACS implementation is the low-area fallback: it
  uses two clocks per symbol and roughly halves ACS logic. It is not the default because it
  reduces coded-symbol throughput.
- A deeply pipelined one-symbol-per-clock design requires two or more independent metric
  contexts (interleaved framed codewords); state memory and control scale with the context count.

Acceptance requires hard and soft bit identity, tie behavior, punctured-zero LLR handling, and
the existing BER/waterfall bounds. The block must publish traceback latency, minimum frame gap,
and symbols/clock for each architecture.

## AGC

The current loop applies `gain[n]`, derives `|y[n]|`, and commits `gain[n+1]` on the same
accepted transfer. The multiply/rescale, magnitude approximation, error calculation and clamp
therefore form one feedback path.

The preferred option registers the applied output and updates gain from that registered
magnitude one cycle later. Sample throughput stays at one per clock and datapath latency grows
from one to two cycles, but the control loop gains one unit delay. This must be a parameterized
architecture because it changes the exact gain trajectory even though the steady-state target
is unchanged.

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

Trade-offs:

- Fully staged serial CIC remains one input sample per clock but adds about `N-1` clocks of group
  delay and `N*W` pipeline state per I/Q path.
- Pipelining the x4 prefix keeps four-sample throughput but adds lane-history registers and a
  fixed beat of latency; two lanes approximately halve the prefix width and peak throughput.
- Time-multiplexing a single adder minimizes area but needs `N` clocks per accepted sample and is
  only suitable when the fabric clock is well above the sample rate.

Acceptance requires bit identity after the declared delay/phase adjustment, impulse and random
wrap-around vectors, runtime backpressure, and unchanged CIC droop characterization.

## FFT family

In an SDF stage the butterfly difference is twiddle-multiplied, scaled and written into the delay
feedback on the same beat. The iterative core has an equivalent read/butterfly/write schedule in
BRAM. A register in either feedback edge changes which operands meet unless the schedule or the
number of independent contexts also changes.

Two explicit options should be evaluated:

1. A folded SDF stage splits butterfly/twiddle work over two clocks. Area stays close to the
   current core and timing improves, but throughput becomes one sample every two clocks.
2. An interleaved stage pipelines the butterfly and alternates two independent frames/channels.
   Aggregate throughput returns to one sample per clock, at the cost of duplicated delay state,
   stricter framing, and roughly doubled storage.

The iterative FFT should independently add registered butterfly sub-stages to its existing
read/compute/write FSM. It keeps the lowest-area position but increases `cycles_per_frame`; this
is preferable to making the streaming SDF default slower. The x2 parallel FFT inherits the SDF
choice in both sub-cores and must report aggregate samples/clock, not just clock frequency.

Acceptance requires bit identity versus `fft_fixed_model` for scaled mode, the existing BFP
exponent/overflow contract, forward/inverse operation, exact frame markers under backpressure,
and published latency, frame gap, samples/clock, LUT/FF/BRAM/DSP and achieved fmax.

## Landing policy

Each family is a separate change series: architecture parameter and model first, focused tests
second, then ECP5 and Artix-7 implementation results. A new option may become the default only
when its stream contract and numerical behavior are documented and downstream composites have
been re-verified. Raw measurements refresh `fmax_mhz`/`fmax_min`; the 100 MHz target remains
manually reviewed and is checked explicitly with `impl/run.py --target-gate`.
