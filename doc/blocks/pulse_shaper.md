# Pulse shaper (RRC)

`LiteDSPPulseShaper` — `litedsp.filter.pulse_shape` — category `filter`

latency: 33 samples · CSR: yes · bypass: no

## Overview

Root-raised-cosine pulse-shaping interpolator (``sps`` samples/symbol).

An interpolating polyphase FIR loaded with RRC taps: maps a 1-sample-per-symbol I/Q stream
to ``sps`` samples/symbol with matched-filter pulse shaping. Use the same RRC at RX.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `sps` | `4` | int | Samples per symbol (interpolation factor); the output rate is sps x the input rate. Also the number of polyphase branches of the underlying FIR interpolator. |
| `span` | `8` | int | Filter span in symbols (n_taps = sps*span + 1). Longer span = closer to the ideal RRC (better stopband/ISI) at the cost of more taps and latency. |
| `beta` | `0.35` | float | RRC roll-off factor, 0 < beta <= 1. Excess bandwidth fraction; the occupied bandwidth is (1 + beta) x symbol_rate / 2 per side. Smaller = sharper but longer pulses. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `core_config` (read-only, 32 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `taps` | `0` | FIR taps N. |
| `[31:16]` | `rate` | `0` | Interpolation factor L. |

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_pulse_shape.py` (bit-exact/SNR under randomized backpressure).
