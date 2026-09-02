# Bitstream (sigma-delta/PDM) decimator

`LiteDSPBitstreamDecimator` — `litedsp.filter.bitstream` — category `filter`

latency: 1 sample · CSR: yes · bypass: no

## Overview

1-bit sigma-delta / PDM bitstream -> PCM samples through a runtime-rate sinc^N decimator.

``sink.data`` is one modulator bit per beat (``1`` = +1, ``0`` = -1); ``source`` emits one
signed ``data_width`` sample per ``rate`` bits, ``+FS`` for a 100 % density stream at the
reset configuration (``rate = decimation``, ``shift = bitstream_shift(...)``). ``rate`` and
``shift`` are runtime controls sized for ``r_max`` (default: ``decimation``), exactly as
for :class:`~litedsp.filter.cic.LiteDSPCICDecimatorRuntime` (``staged=True`` selects its
timing-friendly architecture). Shared by the motor-control sigma-delta current sense and
the audio PDM microphone receiver.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `decimation` | `64` | int | Reset decimation rate (bits per output sample), >= 2. |
| `n_stages` | `4` | int | Sinc order N (integrator/comb stages): 3 for current sense, 4-5 for audio PDM. |
| `diff_delay` | `1` | int | Comb differential delay M (usually 1). |
| `r_max` | — | none | Maximum runtime rate the datapath is sized for (default: ``decimation``). |
| `staged` | `False` | bool | Use the register-chained, pipelined CIC architecture (needs ``rate >= 2*n_stages + 4``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `rate` (read-write, 7 bits, reset `0x40`)

Decimation rate (bits per output sample, 2..r_max).

### `shift` (read-write, 5 bits, reset `0x1`)

Rescale shift; set to bitstream_shift(rate, ...) for the chosen rate.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 677 | 240 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_bitstream.py` (bit-exact/SNR under randomized backpressure).
