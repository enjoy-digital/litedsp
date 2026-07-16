# CFO estimator (coarse)

`LiteDSPCFOEstimator` — `litedsp.comm.cfo_est` — category `comm`

latency: 0 samples · CSR: yes · bypass: no

## Overview

Coarse CFO estimator: delay-conjugate-multiply autocorrelation + CORDIC angle.

Schmidl-Cox / van de Beek style acquisition front-end. For a signal that repeats with
period ``D = delay`` samples (a repeated preamble, or OFDM where the cyclic prefix sits
``D = fft_size`` samples from the symbol tail), each product ``r[n] = x[n]*conj(x[n-D])``
has phase ``2*pi*f_cfo*D`` independent of the modulation, so a carrier frequency offset
survives averaging while data and noise average out. The block free-runs in blocks:
``R = sum r[n]`` is accumulated over ``2**span_log2`` samples — kept exact, no rounding:
the complex product grows to ``2*data_width + 1`` bits and the accumulation adds
``span_log2`` bits — then ``(Re R, Im R)`` is vectored through a CORDIC
(:class:`litedsp.generation.cordic.LiteDSPCORDIC`, ``stages = angle_width``) to get
``angle(R)``, the result is latched with a one-cycle ``estimate_ready`` pulse (counted in
a CSR, optional IRQ via ``with_irq=True``), and the next span starts. The unambiguous
capture range is ``|f_cfo| < 1/(2*D)`` cycles/sample (``|angle| < pi``).

The input stream passes through unchanged (combinational, ``latency = 0``): the estimator
is a monitoring tap that drops into a chain directly in front of a
:class:`litedsp.correction.cfo.LiteDSPDerotator`.

Scaling (why ``delay`` must be a power of two): angles are signed with full circle =
``2**angle_width``, so the latched ``angle = f_cfo*D*2**angle_width``. The derotator
down-mixes by its NCO frequency (``source = sink*exp(-j*2*pi*n*phase_inc/2**phase_bits)``
— the minus sign lives in its conjugating mixer), so cancelling the offset needs
``phase_inc = +f_cfo*2**phase_bits = angle*2**(phase_bits - angle_width)/D``. With
``D = 2**delay_log2`` this is the exact left shift
``phase_inc_correction = angle << (phase_bits - angle_width - delay_log2)`` (enforced
non-negative by ``check()``); a non-power-of-two ``D`` would need a hardware divider.
``phase_inc_correction`` can be written as-is to the derotator NCO ``phase_inc``.

## Parameters

| Parameter | Default | Type | Description |
|---|---|---|---|
| `data_width` | `16` | int | Sample width in bits (signed Qm.n; default Q1.15). |
| `delay` | `16` | int | Autocorrelation lag ``D`` in samples (power of two >= 2): the repetition period of the training signal (preamble repeat length / OFDM CP distance = FFT size). Sets the capture range ``|f_cfo| < 1/(2*delay)`` and the delay-line depth. |
| `span_log2` | `8` | int | Accumulation span as a power of two: one estimate per ``2**span_log2`` samples. Longer spans average more noise (estimator variance ~ 1/span) but slow the update rate; the first span after reset includes ``delay`` zero products while the delay line fills. |
| `angle_width` | `16` | int | Angle resolution in bits (full circle = 2**angle_width); sets the CORDIC stage count. |
| `phase_bits` | `32` | int | Phase-accumulator width of the derotator NCO that ``phase_inc_correction`` is scaled for (requires ``phase_bits >= angle_width + log2(delay)``). |
| `with_irq` | `False` | bool | Add a LiteX EventManager interrupt on the block's trigger event. |

## Ports

| Port | Direction | Layout |
|---|---|---|
| `sink` | sink | iq |
| `source` | source | iq |

Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).

## Register Map

### `angle` (read-only, 16 bits)

Latched autocorrelation angle (signed two's complement, full circle = 2**angle_width): CFO = angle / (2**angle_width * delay) cycles/sample.

### `phase_inc` (read-only, 32 bits)

Latched derotator correction (angle rescaled to NCO phase units): write to the derotator NCO phase_inc to cancel the estimated CFO (the derotator's down-mixer applies the minus sign).

### `count` (read-only, 32 bits)

Estimates since reset/clear.

### `control` (read-write, 1 bit)

| Bits | Field | Reset | Description |
|---|---|---|---|
| `[0]` | `clear` | `0` | Clear the estimate counter. (pulse) |

## FPGA Resources

| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |
|---|---|---|---|---|---|---|
| ecp5 | 4805 | 1764 | 0 | 4 | 115.0 | — |
| xilinx | 1527 | 1650 | 0 | 5 | — | — |

Resources are measured by the `impl/` flows at the registry configuration; the fmax floor is the regression guard (85% of baseline P&R); an optional target is the independent engineering objective. Regenerate with `python3 impl/report.py` (budget-gated in CI).

## Verification

Golden-model tests: `test/test_cfo_est.py` (bit-exact/SNR under randomized backpressure).
