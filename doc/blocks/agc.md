# AGC

`LiteDSPAGC` — `litedsp.level.agc` — category `level`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Automatic gain control: drives |output| toward ``target``.

Estimates the input magnitude (alpha-max-beta-min), integrates the error into a gain
(``gain += (target - |x|) >> mu``, clamped to ``[0, gain_max]``), and applies it
(round + saturate). ``mu`` sets the loop time constant. Gain is Q?.``gain_frac``.
``railed`` is asserted while the loop sits at a gain clamp (overload/underrange); with
``with_irq=True`` its rising edge raises an interrupt (``ev.railed``).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `gain_frac` | `8` | int | Fractional bits of the gain (gain register is data_width + gain_frac bits, reset to 1.0 = 2**gain_frac). More bits = finer gain resolution but a wider multiplier. |
| `mu` | `8` | int | Loop-gain exponent; each accepted sample updates gain by (target - |x|) >> mu. Larger = slower, smoother AGC (longer time constant); smaller = faster but may pump. |
| `gain_max` | — | none | Upper clamp of the gain integrator, in 2**-gain_frac units. Defaults to the full gain register range (2**(data_width + gain_frac) - 1); lower it to bound the maximum gain. |
| `beta_shift` | `2` | int | Beta exponent of the alpha-max-beta-min magnitude estimate (|x| ~ max + min >> beta_shift). 2 is the usual multiplier-free compromise (~4% peak error). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |
| `delayed_feedback` | `False` | bool | When true, apply each magnitude observation on the following accepted sample.  This inserts one sample of control-loop delay without making the trajectory depend on stalls. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `target` (read-write, 17 bits, reset `0x4000`)

Target output magnitude.

### `gain` (read-only, 24 bits)

Current gain (Q?.frac).

### `config` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[1:0]` | `feedback_delay` | `0` | Accepted-sample delay in the gain feedback path. |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 349 | 75 | 0 | 4 | 90.4 | 100.0 |
| xilinx | 197 | 75 | 0 | 2 | 87.8 | 100.0 |
| xilinx_au | 173 | 75 | 0 | 2 | 168.6 | 100.0 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_agc.py` (bit-exact/SNR under randomized backpressure).
