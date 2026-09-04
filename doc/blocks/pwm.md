# 3-phase PWM

`LiteDSPPWM` — `litedsp.motor.pwm` — category `motor`

latency: variable (data-dependent) · CSR: yes · bypass: no

## Overview

Center-aligned three-phase PWM with dead time, fault latch and ADC trigger (sink-only).

A triangular carrier counts 0 -> ``period`` -> 0 (``2*period`` cycles per PWM period,
counting up from reset). ``sink`` (three signed duties, ``-1.0..+1.0`` = 0..100 %) is
accepted once per period, on the carrier valley (``count == 0`` at the end of the
down-count) -- so a control loop feeding this block runs at exactly the PWM rate, paced by
backpressure. Accepted duties are converted to compare values ``cmp = round(period*(duty
+ 1)/2)`` by one time-shared multiplier and applied at the *next* valley (double
buffering: glitch-free, one period of latency); if no sample is offered in a window the
previous duties are held and the sticky ``missed`` flag is set.

``pwm_h[k]`` is high while ``count < cmp[k]`` (``2*cmp - 1`` cycles centered on the
valley), ``pwm_l[k]`` is its complement; on every edge both outputs stay low for
``dead_time`` cycles. ``enable`` gates the outputs; a ``fault``
input (over-current comparator, driver
fault) switches all six outputs off within one cycle and latches ``fault_latched`` until
``fault_clear`` (with ``with_irq=True``: ``ev.fault``; ``ev.period`` fires every valley
for a CPU-driven loop). ``trigger`` pulses when the carrier passes ``trigger_count`` on the
``trigger_direction`` slope (0: at/after the valley while counting down, 1: while counting
up) -- the sample point for shunt current measurement in the zero vector.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `period_width` | `16` | int | Width of the carrier counter / ``period`` control (period >= 4 cycles). |
| `dead_time_width` | `8` | int | Width of the ``dead_time`` control (cycles, up to 2**width - 1). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `period` (read-write, 16 bits, reset `0x3e8`)

Half PWM period in cycles (carrier peak); PWM period = 2*period.

### `dead_time` (read-write, 8 bits)

Dead time in cycles inserted at every gate-signal edge.

### `control` (read-write, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `enable` | `0` | Enable the gate outputs. |
| `[1]` | `fault_clear` | `0` | Clear the fault latch. (pulse) |
| `[2]` | `missed_clear` | `0` | Clear the missed flag. (pulse) |

### `trigger` (read-write, 17 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[15:0]` | `count` | `0` | Carrier value at which the ADC trigger pulses. |
| `[16]` | `direction` | `0` | Carrier counting direction. ``0b0``: Counting down / valley side.; ``0b1``: Counting up / peak side. |

### `status` (read-only, 2 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `fault_latched` | `0` | Outputs forced off by a fault. |
| `[1]` | `missed` | `0` | A PWM window had no duty sample. |

### `count` (read-only, 16 bits)

Carrier counter.

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 310 | 223 | 0 | 1 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_pwm.py` (bit-exact/SNR under randomized backpressure).
