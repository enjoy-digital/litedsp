# Sigma-delta current sense

`LiteDSPSigmaDeltaFilter` — `litedsp.motor.sense` — category `motor`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Isolated sigma-delta current sense: per-phase sinc^N demodulators + fast trip path.

``sinks[k]`` carry the modulator bitstreams of the ``n_channels`` phases (consumed in
lock-step); ``source`` emits the demodulated currents (``abc_layout`` for three channels,
``real_layout`` for one) at ``1/rate`` of the bit rate through the runtime-rate
:class:`~litedsp.filter.bitstream.LiteDSPBitstreamDecimator` (``rate``/``shift``
controls, reset from ``decimation``). Every phase also feeds a second, short sinc^N of fixed
``fast_decimation`` whose output is compared against ``threshold``: an over-current trips
the per-phase sticky ``overcurrent`` bits (cleared by ``clear``; ``ev.overcurrent`` with
``with_irq=True``) within ``fast_decimation`` bits, independently of the slower control
path. Latency 1 (as the runtime CIC).

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `n_channels` | `3` | int | Number of phases (1 or 3). |
| `decimation` | `64` | int | Reset decimation rate of the control path (bits per sample). |
| `n_stages` | `3` | int | Sinc order of both paths (3 is the usual choice for current sense). |
| `r_max` | `256` | int | Maximum runtime rate of the control path. |
| `fast_decimation` | `16` | int | Fixed decimation of the over-current path (short, e.g. 8-32 bits). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sinks[0]` | sink | real |
| `sinks[1]` | sink | real |
| `sinks[2]` | sink | real |
| `source` | source | abc |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `rate` (read-write, 9 bits, reset `0x40`)

Control-path decimation rate (bits per sample).

### `shift` (read-write, 5 bits, reset `0x3`)

Control-path rescale shift (bitstream_shift(rate, ...)).

### `threshold` (read-write, 16 bits, reset `0x7fff`)

Over-current trip magnitude (fast path, per-unit).

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the trip flags. (pulse) |

### `status` (read-only, 3 bits)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[2:0]` | `overcurrent` | `0` | Sticky per-phase trips. |

### `fast_value0` (read-only, 16 bits)

Last fast-path sample of phase 0.

### `fast_value1` (read-only, 16 bits)

Last fast-path sample of phase 1.

### `fast_value2` (read-only, 16 bits)

Last fast-path sample of phase 2.

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_sense.py` (bit-exact/SNR under randomized backpressure).
