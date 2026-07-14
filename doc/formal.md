# Formal verification of the stream fabric (SymbiYosys)

The plumbing blocks — the handshake-heavy, low-arithmetic blocks every chain is built from — are
formally verified with SymbiYosys (yosys + smtbmc/bitwuzla, OSS CAD Suite) against the LiteX
stream contract, under **fully arbitrary traffic and backpressure**: every sink
valid/first/last/payload and every source ready is a free `(* anyseq *)` input, so the solver
explores *all* producer/consumer timings, not a random sample of them.

**Claim earned**: the stream fabric is formally verified for **zero sample loss and zero
duplication under arbitrary backpressure** (at the configs/depths below).

## Running

```
python3 formal/run_formal.py                     # all registry entries
python3 formal/run_formal.py --block skid_buffer # a selection
python3 formal/run_formal.py --list              # list registry entries
```

`formal/wrapper.py` emits each block to Verilog exactly like sim/impl do
(`litedsp/verilog.py`), generates a `<name>_formal.sv` top binding the
`formal/stream_props.sv` checkers, and `formal/run_formal.py` generates + runs one `.sby` per
block (nonzero exit on any failure). The nightly CI `formal` job runs the full suite.

## Properties

Per block, with reset asserted at cycle 0 (standard sby setup):

1. **Stability** (the LiteX stream contract): once `valid` is asserted with `ready` low, `valid`
   must stay asserted and the transfer contents (payload + `first`/`last`) must be unchanged on
   the next cycle. *Assumed* on the DUT's sinks (the anyseq environment is a well-behaved
   producer), *asserted* on its sources.
2. **Token conservation** (no loss / no duplication): a signed running difference accumulates
   `IN_WEIGHT` per input transfer and `-OUT_WEIGHT` per output transfer (the weights encode the
   block's rate contract, e.g. `iq_pack` ratio 2 is 1:2) and must stay within
   `[MIN_DIFF, MAX_DIFF]` **forever**. The upper bound is the block's declared latency +
   internal buffering (a lost sample would let the difference grow past it); the lower bound
   means outputs never run ahead of consumed input (no duplication).
3. **No valid-from-nowhere**: for registered-output blocks, source `valid` stays low until the
   first sink transfer after reset.
4. **Cover** (anti-vacuity guard): every block additionally proves *reachability* of 4 output
   transfers, and (where architecturally possible) of a source stall with `valid` high — an
   over-constrained setup fails the cover task instead of silently proving nothing.

Multi-endpoint blocks also get lockstep/exclusivity assertions: `split`'s sources see exactly
the same transfers, `combine`'s sinks are consumed together, `channel_mux` never drains an
unselected sink, `channel_demux` never asserts valid to an unselected source.

## Results (per block)

All at `data_width=4` (the properties are payload-width-agnostic; small keeps the solver fast).
`prove` = k-induction, holds for **unbounded** time; `bmc` = bounded model check, exhaustive to
depth 30 cycles (the token counters are the only monitor state, so 30 cycles covers many full
fill/drain/refill rounds of these 1-2-entry buffers). Diff bounds are the *proven-tight*
`[MIN, MAX]` of the weighted in/out difference.

| Block | Config | Tokens in:out | Diff bound | Mode | Status |
|---|---|---|---|---|---|
| `skid_buffer`   | pipe_valid + pipe_ready       | 1:1 | [0, +2]  | bmc 30   | PASS |
| `stream_fifo`   | depth=2                       | 1:1 | [0, +2]  | bmc 30   | PASS |
| `delay_d1`      | depth=1 (regressed once)      | 1:1 | [0, +1]  | bmc 30   | PASS |
| `delay_d2`      | depth=2                       | 1:1 | [0, +2]  | bmc 30   | PASS |
| `split`         | n=2, atomic fan-out           | 1:1 | [0, 0]   | prove    | PASS |
| `combine`       | n_channels=2, enable=0b11     | 1:1 | [0, +1]  | bmc 30   | PASS |
| `channel_mux`   | n=2, sel anyconst             | 1:1 | [0, 0]   | prove    | PASS |
| `channel_demux` | n=2, sel anyconst             | 1:1 | [0, 0]   | prove    | PASS |
| `cdc`           | same-domain (see scope)       | 1:1 | [0, 0]   | prove    | PASS |
| `iq_pack`       | ratio=2, first/last tied low  | 1:2 | [0, +2]  | bmc 30   | PASS |
| `iq_unpack`     | ratio=2                       | 2:1 | [-1, 0]  | bmc 30   | PASS |
| `downsampler`   | factor tied to 2              | 1:2 | [-1, +2] | bmc 30   | PASS |
| `upsampler`     | factor tied to 2 (S/H)        | 2:1 | [0, +2]  | bmc 30   | PASS |

The negative lower bounds are architectural, not duplication: `iq_unpack` (comb LiteX
`_DownConverter`) hands out the first sample of a word *before* consuming the word itself, and
the `downsampler`'s kept sample is the *first* of its decimation group, so its output can
precede the group's dropped sample. Both dips are exactly `-(ratio-1)`/`-(factor-1)` and proven
never to exceed it.

Blocks marked `bmc` were tried in `prove` mode first; k-induction does not close on them because
the token invariant alone is not inductive over their internal buffer state (a stalled
unreachable state self-loops through any induction window), and adding the internal-state lemmas
would mean asserting on hierarchical DUT internals — deliberately avoided so the checkers only
see the port-level contract. BMC depth 30 is exhaustive for every input/backpressure pattern of
that length, which for these 1-2-entry blocks exercises every reachable occupancy many times over.

## Checker validation (mutation testing)

The setup was validated by breaking real backpressure handling in the emitted Verilog and
confirming the properties catch it:

- `delay` pipeline advancing while stalled (dropped the `adv` gate): **token FAIL** (loss).
- `delay` `sink_ready` stuck high (accepts while full): **token FAIL**.
- Undriven/over-constrained setups are caught by the cover task (traffic must reach the output).

## Honest scope

- **Formal owns the plumbing; the numerics are owned by co-sim.** Payload *values* through
  arithmetic blocks (FIR, CIC, mixer, ...) are verified bit-exact against NumPy golden models by
  the Verilator co-simulation (`sim/`, `test/`) — formal here proves the *fabric* moves samples
  without loss, duplication, reorder-inducing handshake violations or payload corruption while
  stalled.
- **Tiny configs.** Proofs are at `data_width=4`, FIFO/delay depth 1-2, n=2, ratio/factor=2. The
  handshake logic of these blocks is width-independent and its structure does not change with
  depth/n (same Migen code paths), but the proof formally covers only the listed configs.
- **`cdc` is verified in its same-domain degenerate form only**, where LiteX
  `ClockDomainCrossing` reduces to a combinational passthrough. The async-FIFO path is a
  multi-clock problem outside this single-clock setup; it is LiteX/Migen upstream code, exercised
  by co-sim.
- **Packet framing is out of scope** for `iq_pack`: LiteX's `_UpConverter` deliberately emits a
  *partial* word when `last` arrives mid-word (packet semantics), which breaks pure sample
  accounting, so its sink `first`/`last` are tied low (unframed sample streams — the fabric's
  use case). All other blocks are verified with free-running `first`/`last`.
- **Runtime controls are pinned or stable**: `factor` tied to 2, `sel`/`enable`
  constant-but-arbitrary (`anyconst`). Switching `sel` mid-stall is not stability-preserving by
  design (the mux is combinational) and is not claimed.
- **`delay`, `combine`, `downsampler`, `upsampler` do not propagate `first`/`last`** (sample
  streams carry no framing; Migen emits those source ports as undriven). They are excluded from
  those blocks' stability vector — a *finding* documented here, not a hidden waiver.
- **`split` asserts valid only when all sinks are ready** (atomic fan-out: valid depends on
  ready). This is why its source-stall cover is skipped (unreachable by construction). It
  composes fine with LiteX-style consumers, but a consumer that waits for `valid` before raising
  `ready` on *another* branch could deadlock — a documented property of atomic fan-out, now
  formally pinned down rather than folklore.

Runtime: full suite ~25 s on a desktop (engine `smtbmc bitwuzla`).
