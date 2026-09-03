# Line encoder (NRZI)

`LiteDSPLineEncoder` — `litedsp.comm.line_code` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Bit stream to line code (``[("data", 1)]`` in and out).

``nrzi_s``: the level toggles on a 0 (HDLC / AIS), ``nrzi_m``: toggles on a 1 (rate 1:1,
latency 1). ``manchester``: two chips per bit, ``b`` then ``~b`` (a 1 is high-then-low);
``diff_manchester``: a transition mid-bit always, a transition at the bit start for a 0
(rate 2:1, the sink accepts one bit per two chips). ``invert`` flips the output;
``phase_rst`` restarts the chip phase / level.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `code` | `"nrzi_s"` | str | Choices: `nrzi_s`, `nrzi_m`, `manchester`, `diff_manchester`. |
| `invert` | `False` | bool |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | real |
| `source` | source | real |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `invert` | `0` | Invert the line. |
| `[1]` | `phase_rst` | `0` | Restart the chip phase / level. (pulse) |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 12 | 7 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_line_code.py` (bit-exact/SNR under randomized backpressure).
