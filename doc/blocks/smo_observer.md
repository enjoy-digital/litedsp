# Sliding-mode observer

`LiteDSPSMObserver` — `litedsp.motor.observer` — category `motor`

latency: 19 samples · CSR: yes · bypass: no

## Overview

Sensorless sliding-mode back-EMF observer (PMSM, stationary alpha/beta frame).

From the measured currents (``sink_i``) and applied voltages (``sink_v``), both per-unit
on ``iq_layout`` and consumed together, a current model per axis
``ih += g_v*(v - emf - z) - g_r*ih`` with the sliding term ``z = k_sm*sign(ih - i)`` and
the low-pass filtered back-EMF ``emf += (z - emf) >> lpf_shift`` reconstructs the back-EMF
vector; ``source`` is its angle ``atan2(-emf_alpha, emf_beta)`` (CORDIC vectoring), i.e.
the rotor electrical angle for positive speed (opposite sign at negative speed: resolve
with the tracker's speed sign). Gains are per-unit: ``g_v = w_b*Ts/L_pu``, ``g_r = R_pu *
w_b*Ts/L_pu`` (signed Q4.12); ``k_sm`` is the sliding gain magnitude, to be set with the
operating point at roughly half the back-EMF magnitude (``~0.35*w_pu`` for ``psi_pu =
0.6``): too small loses the sliding regime, too large adds chatter at low speed. The
estimate lags the rotor by a constant bounded by the filter phase ``atan2(a*sin(d), 1 -
a*cos(d))`` (``a = 1 - 2**-lpf_shift``, ``d`` = angle step per sample). Feed the angle to
:class:`LiteDSPAngleTracker` for a smooth estimate and speed. Latency ``stages + 3``
(CORDIC).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `angle_width` | `16` | int | Output angle width (full turn = 2**angle_width). |
| `gain_width` | `16` | int | Width of the signed observer gains. |
| `gain_frac` | `12` | int | Fractional bits of the gains (1.0 = 2**gain_frac). |
| `stages` | — | none | CORDIC iterations (defaults to ``data_width``). |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink_i` | sink | iq |
| `sink_v` | sink | iq |
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `g_v` (read-write, 16 bits, reset `0x400`)

Voltage gain w_b*Ts/L_pu (signed Q4.12).

### `g_r` (read-write, 16 bits)

Resistive gain R_pu*w_b*Ts/L_pu (signed Q4.12).

### `k_sm` (read-write, 16 bits, reset `0x2000`)

Sliding gain magnitude (per-unit).

### `control` (read-write, 9 bits, reset `0x3`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[3:0]` | `lpf_shift` | `3` | Back-EMF low-pass shift. |
| `[8]` | `clear` | `0` | Reset the observer state. (pulse) |

### `emf_alpha` (read-only, 17 bits)

Back-EMF alpha.

### `emf_beta` (read-only, 17 bits)

Back-EMF beta.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 2775 | 873 | 0 | 4 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_observer.py` (bit-exact/SNR under randomized backpressure).
