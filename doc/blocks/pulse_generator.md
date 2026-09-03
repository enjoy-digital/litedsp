# Pulse generator

`LiteDSPPulseGenerator` — `litedsp.radar.timing` — category `radar`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Transmit pulse train: a linear-FM chirp of ``pulse_len`` samples every ``pri`` samples.

Source-only block: an internal :class:`LiteDSPChirp` (held in reset between pulses, so each
pulse restarts from the ``start`` / ``rate`` words, see
``litedsp.radar.waveform.chirp_words``) is framed (``first`` on the first chirp sample,
``last`` on the last) and followed by zeros up to the PRI. ``enable`` runs CPIs of
``n_pulses`` back to back; ``single`` with a ``trigger`` pulse sends one pulse. Outputs:
``tx`` (during the pulse), ``pulse_start`` (one cycle at the first sample), ``running``
and ``pulse_count``. ``pulse_len``, ``pri`` and ``n_pulses`` are runtime. One bubble per
pulse start (the chirp's first sample follows its reset release).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `pulse_len` | `32` | int |  |
| `bandwidth` | `0.5` | float |  |
| `pri` | `128` | int |  |
| `n_pulses` | `16` | int |  |
| `pri_width` | `24` | int |  |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `start` (read-write, 32 bits, reset `0xc0000000`)

Chirp start frequency word.

### `rate` (read-write, 32 bits, reset `0x4000000`)

Chirp frequency increment per sample.

### `timing` (read-write, 32 bits, reset `0x100020`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `pulse_len` | `32` | Pulse length (samples). |
| `[31:16]` | `n_pulses` | `16` | Pulses per CPI. |

### `pri` (read-write, 24 bits, reset `0x80`)

Pulse repetition interval (samples).

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `0` | Run CPIs continuously. |
| `[1]` | `single` | `0` | One pulse per trigger. |
| `[2]` | `trigger` | `0` | Start a single pulse. (pulse) |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `running` | `0` | A pulse train is in progress. |
| `[1]` | `tx` | `0` | Transmitting. |

### `pulse_count` (read-only, 32 bits)

Pulses sent since reset.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 402 | 143 | 2 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_timing.py` (bit-exact/SNR under randomized backpressure).
