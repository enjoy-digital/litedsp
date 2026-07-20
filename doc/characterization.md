# DSP quality characterization

Datasheet-grade quality metrics for the LiteDSP blocks, measured by `char/run_char.py`
on the NumPy golden models (`test/models.py`; the CORDIC through a Migen simulation).
The golden models are held bit-exact / SNR-equivalent to the RTL by the co-simulation
tests in `test/` and `sim/`, so these numbers characterize the gateware itself.

*Guaranteed* is the checked-in baseline (`char/budgets.json`) with the gate tolerance
applied (3% of the baseline, 0.01 absolute
minimum, direction-aware); CI fails if a measurement crosses it. Regenerate with
`python3 char/run_char.py --update --report` after a deliberate quality change.

## nco

NCO/DDS, `lut_depth=1024`, `phase_bits=32`, 16-bit I/Q; 8192-sample records. `sfdr_lut_exact_db` uses LUT-exact increments (amplitude-quantization limit); the other metrics are the worst case over a 7-point `phase_inc` sweep including near-rational/irrational-ish increments, where performance is phase-truncation limited (~6 dB per LUT address bit).

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `enob_bits` | bits | 8.85 | >= 8.58 |
| `noise_floor_dbfs` | dBFS | -52.02 | <= -50.46 |
| `sfdr_db` | dB | 58.61 | >= 56.85 |
| `sfdr_lut_exact_db` | dB | 103.47 | >= 100.37 |

## cordic

CORDIC rotation mode, 16-bit data/angle, 16 stages (Migen simulation). ENOB of a 0.92 FS tone rotated through a full circle (256 angles).

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `enob_bits` | bits | 12.71 | >= 12.32 |

## mixer

Complex mixer, down-conversion of a 0.76 FS tone at f=0.123 with a LUT-exact quadrature NCO LO at f=1/64; rejection of the f_sig+f_lo image (isolates mixer arithmetic; rounding-noise-floor limited).

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `image_rejection_db` | dB | 117.56 | >= 114.03 |

## fir

FIR low-pass `firwin_lowpass(63, 0.2)` quantized to Q1.15. Realized response of the quantized taps (impulse -> FFT); passband f<=0.15, stopband f>=0.25.

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `passband_ripple_db` | dB | 0.02 | <= 0.03 |
| `stopband_atten_db` | dB | 54.97 | >= 53.32 |

## cic

CIC decimator, `diff_delay=1`, 16-bit. Max |measured - theoretical| droop over the output passband (f_out 0.05..0.25) per (decimation R, n_stages N).

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `droop_err_r16_n3_db` | dB | 0.00 | <= 0.01 |
| `droop_err_r16_n4_db` | dB | 0.00 | <= 0.01 |
| `droop_err_r4_n3_db` | dB | 0.00 | <= 0.01 |
| `droop_err_r4_n4_db` | dB | 0.00 | <= 0.01 |
| `droop_err_r8_n3_db` | dB | 0.00 | <= 0.01 |
| `droop_err_r8_n4_db` | dB | 0.00 | <= 0.01 |

## agc

AGC, `mu=8`, `gain_frac=8`, two-accepted-sample pipelined feedback. Constant-envelope tone at 25% of target: samples to settle within +-5% of target, residual level error, and overshoot (alpha-max-beta-min magnitude, boxcar-smoothed).

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `overshoot_pct` | % | 0.00 | <= 0.01 |
| `settling_samples` | samples | 30.00 | <= 30.90 |
| `steady_state_error_pct` | % | 0.72 | <= 0.75 |

## clipper

Clipper at 50% clip depth (threshold = half the two-tone peak). Two tones at f=0.101/0.117: 3rd-order intermodulation distortion of the clipped output.

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `imd3_dbc` | dBc | 15.45 | >= 14.99 |

## cfr

CFR peak cancellation, `pulse_span=16`, pulse cutoff 0.2, 16-bit. OFDM-like Gaussian I/Q (subcarriers over |f|<=0.2, ~11 dB input PAPR), threshold at the 7 dB PAPR target: PAPR reduction (max/mean power), and RMS EVM of the below-threshold samples vs the delay-aligned input (pulse-tail leakage). Single-engine, single-pass: the residual PAPR is set by busy-skipped peaks and the alpha-max-beta-min estimate spread.

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `evm_below_threshold_pct` | % | 1.62 | <= 1.67 |
| `papr_reduction_db` | dB | 1.57 | >= 1.52 |

## dc_blocker

DC blocker, high-precision notch (`pole_shift=5`, `precision_bits=8`, 16-bit). 0.95 FS DC step + -30 dBFS tone at f=1/64: rejection of the steady-state DC residual (|mean| over 128 settled tone periods). Worst-case bound -6.02*(15 + p - pole_shift) = -108.4 dBFS; the measured residual is exactly 0 (no leak deadband, DC-free error-feedback requantizer), so the metric reports the 140 dB cap.

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `dc_rejection_db` | dB | 140.00 | >= 135.80 |

## window

Window block, hann, n=64, 16-bit coefficients. Peak sidelobe level of the realized (quantized, rounded) window shape.

| Metric | Unit | Measured | Guaranteed |
|---|---|---|---|
| `sidelobe_level_db` | dB | 31.47 | >= 30.53 |
