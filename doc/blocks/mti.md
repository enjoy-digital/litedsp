# MTI canceller

`LiteDSPMTICanceller` — `litedsp.radar.mti` — category `radar`

latency: 2 samples · CSR: yes · bypass: yes

## Overview

Two- or three-pulse MTI canceller on framed pulses (one frame = ``n_range_bins`` beats).

Range bin ``r`` of the previous ``order - 1`` pulses is kept in ``order - 1`` RAMs indexed
by a range counter that ``first`` resets. Runtime ``mode`` 0 subtracts the previous pulse
(``y = x - x1``), mode 1 the three-pulse binomial (``y = x - 2 x1 + x2``, needs
``order == 3``); the difference is rescaled by ``shift`` (default ``mode + 1``, the
canceller's DC gain, so the output never saturates). Stationary clutter cancels exactly;
a target moving ``f`` cycles per pulse is weighted ``|2 sin(pi f)|`` (``4 sin^2(pi f)``).
Latency 2 (the history RAMs' registered read); ``bypass`` passes pulses through unchanged.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `n_range_bins` | `64` | int |  |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `order` | `3` | int |  |
| `shift` | — | none | Output rescale shift (defaults to data_width - 1). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit, reset `0x1`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `mode` | `1` | 0: 2-pulse, 1: 3-pulse canceller. |

### `bypass` (read-write, 1 bit)

Bypass block (passthrough).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 690 | 192 | 2 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_mti.py` (bit-exact/SNR under randomized backpressure).
