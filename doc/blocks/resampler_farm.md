# Resampler farm

`LiteDSPResamplerFarm` — `litedsp.rate.farm` — category `rate`

latency: 32 samples · CSR: yes · bypass: no

## Overview

Decimate-by-R complex FIR for ``n_channels`` streams sharing one serial-MAC engine.

Each channel behaves bit-exactly like its own
:class:`~litedsp.filter.fir_poly.LiteDSPFIRDecimator` (same taps for all channels this
landing; per-channel coefficient banks are a documented follow-up), but the MAC datapath,
coefficient ROM and control FSM are instantiated once and time-shared: only the sample
history is banked per channel, in a single channel-major RAM
(``address = {channel, pointer}``).

**Channel convention** (composes with :mod:`litedsp.stream.route`): the input side uses
the :class:`~litedsp.stream.route.LiteDSPChannelMux` convention of ``n`` per-channel I/Q
``sinks`` with an internal TDM — the farm scans the sinks in fixed round-robin order,
waiting on each in turn, so all channels must run at the same average rate (a stalled
channel backpressures the farm). The output is a single channel-tagged decimated stream:
``iq_layout`` plus a ``channel`` payload field. It is
:class:`~litedsp.stream.route.LiteDSPChannelDemux`-compatible — fan back out with::

    self.comb += [
        farm.source.connect(demux.sink, omit={"channel"}),
        demux.sel.eq(farm.source.channel),
    ]

**Resources** (ECP5, Yosys synth, defaults: 4 channels x 32 taps, R=8, 16-bit): the farm
is 888 LUT / 106 FF / 2 DSP vs 1880 LUT / 416 FF / 8 DSP for 4 separate
``LiteDSPFIRDecimator`` instances — 2.1x fewer LUTs, 3.9x fewer FFs and 4x fewer DSPs
(one engine instead of four), with the per-channel cost reduced to the history-RAM
segment. Throughput is shared: one output costs ``n_taps`` MAC cycles, so the aggregate
input rate is bounded by ``f_clk * R/(R + n_taps + 2)`` samples/s across all channels
(``self.cycles_per_output``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_channels` | `4` | int | Number of time-shared channels (sinks). Adds only history-RAM depth per channel; the MAC engine, coefficient ROM and FSM are shared. |
| `n_taps` | `32` | int | Number of FIR taps. |
| `decimation` | `8` | int | Integer decimation factor. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `coefficients` | — | none | Coefficient list (signed integers, quantized via litedsp.filter.design). |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | iq |
| `sinks[1]` | sink | iq |
| `sinks[2]` | sink | iq |
| `sinks[3]` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `taps` | `0` | FIR taps N. |
| `[23:16]` | `rate` | `0` | Decimation factor R. |
| `[31:24]` | `channels` | `0` | Time-shared channels. |

### `coeff_reset` (read-write, 1 bit)

Reset the coefficient write pointer to tap 0 (write to strobe).

### `coeff` (read-write, 16 bits)

Write the next FIR coefficient (auto-incrementing tap index, shared by all channels).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 920 | 106 | 0 | 2 | 73.4 | — |
| xilinx | 450 | 80 | 0 | 2 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_farm.py` (bit-exact/SNR under randomized backpressure).
