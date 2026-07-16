# NCO (DDS)

`LiteDSPNCO` — `litedsp.generation.nco` — category `generation`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Numerically-Controlled Oscillator (a.k.a. DDS).

Generates a complex exponential ``cos(2*pi*f*t) + j*sin(...)`` from a phase accumulator and
a pair of cos/sin lookup ROMs. The output frequency is set by ``phase_inc`` (Hz =
``phase_inc * f_clk / 2**phase_bits``).

The source is free-running: ``valid`` is asserted once the first sample is in the output
register and stays asserted; the phase only advances when a sample is accepted
(``valid & ready``), so downstream backpressure never drops or repeats samples.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `lut_depth` | `1024` | int | Cos/sin lookup ROM depth (power of two); sets the phase-quantization spur floor. |
| `quarter_wave` | `False` | bool | Store a single quarter-wave sine table (depth lut_depth/4 + 1) and reconstruct cos/sin by symmetry (4x ROM saving) at the cost of a little output mux logic. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `phase_inc` (read-write, 32 bits)

Phase increment (sets output frequency).

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) |
|---|---|---|---|---|---|
| ecp5 | 43 | 43 | 2 | 0 | 237.2 |
| xilinx | 65 | 33 | 1 | 0 | 264.8 |

Resources are measured by the `impl/` flows at the registry configuration; the fmax value is the regression floor (85% of the baseline P&R result). Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_nco.py` (bit-exact/SNR under randomized backpressure).
