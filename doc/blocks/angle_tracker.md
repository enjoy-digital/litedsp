# Angle tracker (PLL)

`LiteDSPAngleTracker` — `litedsp.motor.observer` — category `motor`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Type-II tracking loop on an angle stream: filtered angle + speed (angle PLL).

Per accepted sample the wrapped error ``e = angle_in - theta`` drives a
:class:`~litedsp.control.LiteDSPPILoop` (shift gains ``kp_shift``/``ki_shift``, runtime
controls) whose output advances the internal angle ``theta`` (``angle_width + frac_bits``
bits): ``theta += (e >> kp_shift) + integral`` and ``integral += e >> ki_shift`` (error in the
``frac_bits`` domain). The emitted angle is the estimate *for the accepted sample*
(``theta`` before its update, like the carrier loop's NCO phase): a constant-speed input is
tracked with zero steady-state error; the integrator is the ``speed`` (angle units per
sample, Q.``frac_bits``), so the raw noisy angle from an encoder, Hall decoder or observer
becomes a smooth estimate (``theta + speed`` predicts the next sample). Latency 1.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `angle_width` | `16` | int | Angle width (full turn = 2**angle_width). |
| `frac_bits` | `14` | int | Fractional bits of the internal angle / speed accumulators. |
| `kp_shift` | `4` | int | Reset proportional shift (larger = slower). |
| `ki_shift` | `10` | int | Reset integral shift (larger = slower); lock time ~ 6 * 2**(ki_shift - kp_shift) samples. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | angle |
| `source` | source | angle |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `gains` (read-write, 13 bits, reset `0xa04`)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[4:0]` | `kp_shift` | `4` | Proportional shift (larger = slower). |
| `[12:8]` | `ki_shift` | `10` | Integral shift (larger = slower). |

### `speed` (read-only, 32 bits)

Tracked speed: angle units per sample, Q.frac_bits.

### `error` (read-only, 16 bits)

Last phase error.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_observer.py` (bit-exact/SNR under randomized backpressure).
