# PDM receiver

`LiteDSPPDMReceiver` — `litedsp.audio.pdm` — category `audio`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

PDM microphone receiver: :class:`LiteDSPBitstreamInterface` (``mclk`` out at ``sys_clk /
clk_div``, ``mdat`` in; ``dual_edge`` puts two channels on one line, the stereo-microphone
L/R select) feeding one :class:`LiteDSPBitstreamDecimator` (sinc^N, ``decimation``) per
channel, an optional mono :class:`LiteDSPDCBlocker` (``dc_pole_shift``, 8 fractional bits)
and an optional CIC droop-compensation :class:`LiteDSPFIRFilter` (``n_comp_taps``, serial
MAC), interleaved by a :class:`LiteDSPTDMMux` into a channel-tagged TDM source at ``sys_clk
/ (clk_div * decimation)`` frames per second. Source-only (``latency = None``); the
interface's sticky ``overrun`` flags a bit dropped by back-pressure.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int |  |
| `decimation` | `64` | int | Integer decimation factor. |
| `n_stages` | `4` | int | Number of CIC integrator/comb stages (N in the literature). |
| `clk_div` | `16` | int |  |
| `dual_edge` | `True` | bool |  |
| `with_dc_blocker` | `True` | bool |  |
| `dc_pole_shift` | `10` | int |  |
| `with_compensation` | `False` | bool |  |
| `n_comp_taps` | `15` | int |  |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the overrun flag. (pulse) |

### `status` (read-only, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `overrun` | `0` | Sticky: a bit was dropped (back-pressure). |

### `config` (read-only, 30 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `n_channels` | `0` | Channels. |
| `[11:4]` | `clk_div` | `0` | sys_clk / mclk. |
| `[27:12]` | `decimation` | `0` | Bits per output sample. |
| `[28]` | `dc_blocker` | `0` | DC blocker present. |
| `[29]` | `compensation` | `0` | Droop compensation present. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1244 | 675 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pdm.py` (bit-exact/SNR under randomized backpressure).
