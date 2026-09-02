# Peak meter

`LiteDSPPeakMeter` — `litedsp.audio.meter` — category `audio`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Per-channel peak / hold / clip meter on a TDM stream (zero-latency passthrough tap).

Per accepted beat of channel ``c`` with magnitude ``m = |x|``: ``peak[c] = max(m, peak[c] -
max(peak[c] >> decay_shift, 1))`` (exponential fall-back, ``2**decay_shift`` beats per
e-fold, exact convergence to 0), ``hold[c] = max(hold[c], m)`` until ``clear``, and ``m >=
clip_threshold`` increments the saturating 16-bit ``clip_count[c]`` and sets the sticky
``clip`` bit (IRQ ``ev.clip`` on the first clip). A shared :class:`LiteDSPLog2` (LUT) scans
the peaks round-robin into ``peak_log2[c]`` (unsigned Q(int).8 ``log2(peak)``; the host
converts with ``dBFS = 6.02*(L - (data_width - 1))``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `24` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `2` | int |  |
| `decay_shift` | `12` | int | Reset value of the runtime fall-back rate (1..15): ``2**decay_shift`` beats per e-fold. |
| `clip_threshold` | — | none | Magnitude counted as a clip (default full scale ``2**(data_width - 1) - 1``). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | tdm |
| `source` | source | tdm |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear peaks, holds, clip counts and flags. (pulse) |

### `decay_shift` (read-write, 4 bits, reset `0xc`)

Peak fall-back rate: 2**decay_shift beats per e-fold.

### `clip_threshold` (read-write, 24 bits, reset `0x7fffff`)

Magnitude counted as a clip.

### `clip` (read-only, 2 bits)

Sticky per-channel clip flags.

### `peak0` (read-only, 24 bits)

Channel 0 decaying peak magnitude.

### `hold0` (read-only, 24 bits)

Channel 0 peak magnitude since clear.

### `clip_count0` (read-only, 16 bits)

Channel 0 clips since clear (saturating).

### `peak_log20` (read-only, 13 bits)

Channel 0 log2(peak), unsigned Q(int).8.

### `peak1` (read-only, 24 bits)

Channel 1 decaying peak magnitude.

### `hold1` (read-only, 24 bits)

Channel 1 peak magnitude since clear.

### `clip_count1` (read-only, 16 bits)

Channel 1 clips since clear (saturating).

### `peak_log21` (read-only, 13 bits)

Channel 1 log2(peak), unsigned Q(int).8.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 1109 | 188 | 0 | 0 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_meter.py` (bit-exact/SNR under randomized backpressure).
