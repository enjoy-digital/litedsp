# Carrier loop (PLL)

`LiteDSPCarrierLoop` — `litedsp.comm.pll` — category `comm`

latency: 1 sample · CSR: yes · bypass: no

## Overview

Carrier recovery: derotate the input with an internal NCO driven by a PI loop.

Each sample is derotated by ``exp(-j*phase)``; the phase error feeds a :class:`LiteDSPPILoop` whose
output advances the NCO phase (a 2nd-order loop that locks frequency and phase). The
derotated (baseband) signal is the output. ``decision_directed=False`` (PLL) uses the
derotated imaginary part as the error (residual-carrier / tone). ``detector="bpsk"`` uses
``sign(I)*Q`` and ``detector="qpsk"`` uses ``sign(I)*Q - sign(Q)*I``. The latter is the
multiplier-free decision-directed QPSK detector with four stable phase ambiguities.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `phase_bits` | `32` | int | Phase accumulator width in bits. |
| `lut_depth` | `1024` | int | Depth of the NCO cos/sin LUTs (power of 2); addressed by the top log2(lut_depth) phase bits, so deeper LUTs trade memory for lower phase quantization. |
| `kp_shift` | `6` | int | Proportional gain of the PI loop: Kp = 2**-kp_shift. Larger shift = smaller gain (slower, tighter loop). |
| `ki_shift` | `14` | int | Integral (frequency) gain of the PI loop: Ki = 2**-ki_shift per sample. Larger shift = smaller gain (slower frequency acquisition, less jitter). |
| `decision_directed` | `False` | bool | Backward-compatible BPSK selector. When ``detector`` is omitted, False selects PLL and True selects BPSK Costas behavior. |
| `detector` | `"pll"` | str | ``"pll"`` for a residual carrier, ``"bpsk"`` for suppressed-carrier BPSK, or ``"qpsk"`` for decision-directed QPSK. Explicit ``detector`` takes precedence over ``decision_directed``. Choices: `pll`, `bpsk`, `qpsk`. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `frequency` (read-only, 32 bits)

Recovered carrier frequency (PI integrator).

## FPGA Resources

Not characterized yet (no `impl/budgets.json` entry).

## Verification

Golden-model tests: `test/test_pll.py` (bit-exact/SNR under randomized backpressure).
