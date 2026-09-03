# Radar / sonar processing blocks

`litedsp/radar/` adds pulse-Doppler radar and active-sonar processing to the library: pulse
timing, matched-filter pulse compression, clutter cancellation, the slow-time corner turn,
Doppler processing, constant-false-alarm-rate detection in one and two dimensions, peak
extraction with sub-bin centroids, per-CPI target lists and multi-target tracking. The
blocks follow the same conventions as the rest of the library (Q1.15 I/Q samples, elastic
`ready`/`valid` streams, bit-exact NumPy models, Verilator co-simulation, ECP5 budgets in
[`resources.md`](resources.md), generated datasheets under `blocks/`), plus a few radar-specific
stream kinds described below. The end-to-end chain is exercised by
[AN011 — pulse-Doppler radar](app_notes/an011_pulse_doppler_radar.md).

```
                     fast time (one pulse per frame)              slow time (one range bin per frame)
ADC ──► RangeGate ──► PulseCompressor ──► MTICanceller ──► CornerTurn ──► DopplerProcessor ──► CFAR2D ──► PeakExtractor ──► TargetList / AlphaBetaTracker
         (PRI/CPI timer)  (chirp matched filter)  (2/3-pulse)     (N x M RAM)   (window+FFT+|.|)   (cell)       (target)          (CSR readback / track)
```

Sonar uses the same chain at a lower sample rate with a ping generator in front (time-varying
gain and the array/angle blocks are the extended set, see the roadmap at the end).

## Stream kinds and framing

| Kind | Layout | One frame is | Blocks |
|---|---|---|---|
| fast time | `iq_layout` | one pulse: `first` = range bin 0, `last` = range bin N-1 | range gate out, pulse compressor, MTI, corner turn in |
| slow time | `iq_layout` | one range-bin column of M pulses | corner turn out, Doppler processor in |
| map / profile | `real_layout(dw)` (values >= 0) | one range-bin row of M Doppler bins in natural FFT order (bins >= M/2 are negative velocities) | Doppler processor out, CFAR in |
| cell | `cell_layout(dw)`: `data`, `threshold`, `detect` | same framing as its input | CFAR out, peak extractor in |
| target | `target_layout(dw, index_width, frac_bits)`: `range`, `doppler` (unsigned Q.frac_bits bins), `data`, `hit` | one burst per CPI: records (`hit = 1`) then a terminator (`hit = 0`, `data` = record count, `last`); an empty CPI is a single `first & last` terminator | peak extractor out, target list, tracker in |
| track | `track_layout(...)`: `range`, `doppler`, signed `velocity` (Q.velocity_frac bins per CPI, range axis), `id`, `hits`, `hit` | same burst rule; the terminator's `hits` = active track count | tracker out |

Rules that every block in the family shares:

- **Counting from reset.** The window, FFT, Doppler processor, CFARs, peak extractor and corner
  turn count beats and rows from reset; `first`/`last` are checked against those counters and a
  mismatch sets a sticky `frame_error` (cleared by `clear`). Blocks that need it re-synchronise
  the row on `first`. Keep the whole chain in one reset domain and start the source cleanly.
- **Zero padding and flush.** Windowed blocks (CA-CFAR, 2-D CFAR, peak extractor) zero-pad the
  frame edges: `first` clears the window and, after `last`, the trailing cells are pushed out by
  autonomous flush beats with `sink.ready` low. The output therefore has exactly one beat per
  input cell with the same framing; the rate stays 1:1 but the throughput is `M / (M + C)` for
  the 2-D CFAR (C virtual cells per row). The padded edges (and an MTI notch column) see small
  training sums: set the runtime `threshold_min` floor a few times above the noise level.
- **Pulse-compressor alignment.** The two complex FIRs do not carry tags; the compressor
  re-aligns `first`/`last` through a shift register, so range bin r of pulse p leaves at position
  r of output frame p. The first P-1 positions of a frame hold the fold-over of the previous
  pulse's tail (a matched filter needs P-1 samples of history); gate them out or ignore them.
- **Sparse streams.** Target and track bursts are sparse: the CSR-readback blocks (`TargetList`)
  hold one CPI while the next fills, so a list stays readable until the following CPI's
  terminator ("two-CPI lifetime"). Interrupt sources (`ev.cpi`, `ev.list`, `ev.update`) fire
  with the terminators.

## Units

| Quantity | Representation | Host conversion (`litedsp.radar.design`) |
|---|---|---|
| range bin r | integer, or Q.frac_bits after interpolation | `range_bin_metres(fs, c)` = c / (2 fs) (sound speed for sonar) |
| Doppler bin k (natural FFT order) | 0 .. M-1, `k >= M/2` negative | `doppler_bin_velocity(k, M, prf, wavelength)` |
| velocity | signed Q.velocity_frac bins per CPI | multiply by the bin spacing per CPI |
| CFAR `alpha` | unsigned Q(alpha_width - threshold_frac).threshold_frac | `cfar_alpha(pfa, n_training, domain)` (`power` for `i^2 + q^2` cells, `magnitude` for `|.|` cells) |
| tracker gains | unsigned Q1.gain_frac | `alpha_beta_from_index(lam)` (Kalata) / `tracker_gains` |
| chirp | `chirp_words(bandwidth, pulse_len, phase_bits)` start / rate words | `chirp_reference(...)` reproduces `LiteDSPChirp` bit-exactly |

Cells are unsigned magnitudes (`data_width + 1` bits from the alpha-max-beta-min magnitude, or
`2 * data_width + 1` for power); the flow injects the chain `data_width` into every block that
has one, so a mixed 16-bit I/Q / 17-bit cell chain sets `data_width` per block in the netlist.

## Block summary

| Block | Key | Role | Notes |
|---|---|---|---|
| `LiteDSPRangeGate` | `range_gate` | PRI / CPI timer in the sample domain, gated and framed receive window, `tx` / `rx_gate` / `cpi_start` outputs, IRQ per CPI | rate data dependent; `RangeGateDriver.set_pri(s)` / `set_gate` / `start` / `trigger` |
| `LiteDSPPulseCompressor` | `pulse_compressor` | chirp matched filter: two `LiteDSPFIRFilterComplex` (re/im taps from `pulse_compressor_taps`, optional Hamming taper) recombined with saturation, tags re-aligned | `fir_architecture="mac"` for long pulses; PSLR >= 10 dB rect, >= 15 dB Hamming at TBP 16 |
| `LiteDSPMTICanceller` | `mti` | 2-/3-pulse canceller over N range bins (history RAMs), runtime `mode`, bypass | stationary clutter cancels exactly |
| `LiteDSPCornerTurn` | `corner_turn` | N x M x 2dw ping-pong RAM: fast-time frames in, slow-time columns out, `frame_error` | `filled` status |
| `LiteDSPBitReverse` (`analysis/`) | `bit_reverse` | N-beat frame reorder (bit-reversed FFT output to natural order), skips the SDF FFT's fill beats | any payload layout |
| `LiteDSPDopplerProcessor` | `doppler` | window -> scaled FFT over the M pulses -> magnitude (`approx`) or power -> natural order | Hann sidelobes <= -25 dB in the tests |
| `LiteDSPCACFAR` | `ca_cfar` | 1-D cell averaging with guard cells, CA / GO / SO statistic, threshold (floored at `threshold_min`) and decision | `CFARDriver.set_pfa(pfa, domain)`, `set_floor` |
| `LiteDSPCFAR2D` | `cfar_2d` | 2-D box CFAR on map rows: line buffer (4 read ports, replicated by synthesis) + column-sum RAMs + horizontal window, `threshold_min` floor | throughput M / (M + C) |
| `LiteDSPPeakExtractor` | `peak_extractor` | 3x3 local maxima of the detections, parabolic sub-bin interpolation (bit-serial divider), target bursts, IRQ per CPI | plateaus give one record |
| `LiteDSPTargetList` | `target_list` | ping-pong list of `max_targets` records with overflow flag, re-emitted framed, CSR readback | `TargetListDriver.read_targets()` |
| `LiteDSPAlphaBetaTracker` | `alpha_beta_tracker` | gated nearest-neighbour association + alpha-beta filter per track, confirmation / coasting / deletion, track bursts, IRQ per update | `TrackerDriver.set_tracking_index(lam)` |
| `LiteDSPOSCFAR` | `os_cfar` | ordered-statistic CFAR on the CA window (ranked training cell, runtime rank): immune to a neighbouring target or interferer | `OSCFARDriver.set_rank` |
| `LiteDSPClutterMap` | `clutter_map` | per-cell exponential average across scans in RAM (censored / learn-all, freeze, initialisation scan), threshold on the cell's own clutter | `ClutterMapDriver.set_alpha / set_learning` |
| `LiteDSPKalmanTracker` | `kalman_tracker` | the tracker engine with a constant-velocity Kalman update per axis (predicted covariance, bit-serial gains, clamped covariance with `cov_sat`) | `KalmanTrackerDriver.set_noise / set_tracking_index` |
| `LiteDSPBeamformer` | `beamformer` | narrowband phase-shift beams from `n_elements` joined streams, `n_beams` per sample (channel tag), shadow weights committed at a sample boundary | `BeamformerDriver.set_steering(beam, angle, d/lambda, taper)` |
| `LiteDSPMonopulse` | `monopulse` | phase of `a * conj(b)` (mixer + vectoring CORDIC) on `angle_layout` | angle of arrival on the host |
| `LiteDSPPulseGenerator` | `pulse_generator` | source-only chirp pulse train (framed pulse + zeros to the PRI, CPI or single-pulse modes, `tx` / `pulse_start`) | `PulseGeneratorDriver.set_waveform(bw_hz, pulse_s, pri_s)` |
| `LiteDSPTVG` | `tvg` | sonar time-varying gain: log-domain ramp `g0 + k_log log2(r) + k_lin r` through Exp2, bypass at the same latency | `TVGDriver.set_law(dB/decade, dB/bin, g0_dB)` |

Resource budgets (ECP5 synthesis, default parameters) are in [`resources.md`](resources.md); the
generated datasheets under `blocks/` embed them per block. The default geometry (N = 64 range
bins, M = 16 pulses, 16-bit I/Q) keeps every block in the low thousands of LUTs; memory grows
with N x M (corner turn: 2 x N x M x 2dw bits) and with the CFAR box (2-D CFAR line buffer:
(2R + 1) x M cells, replicated per read port).

## Latency and throughput

| Block | Latency | Throughput |
|---|---|---|
| range gate, MTI | fixed (1 / 2 cycles) | 1 sample per cycle |
| pulse compressor | `fir.latency + 1` (`classic`); `None` with `mac` (P / n_macs cycles per sample) | 1 per cycle (`classic`) |
| corner turn, bit reverse, Doppler processor | `None` (a column / frame is buffered) | 1 per cycle after the fill |
| CA-CFAR | `None` (nominal T + G + 4, plus the T + G + 1 flush beats per frame) | 1 per cycle, flush between frames |
| 2-D CFAR | `None` (R rows + C cells + 7) | M / (M + C) |
| peak extractor | `None` | 1 per cycle, `frac_bits + 3` extra cycles per record |
| target list | `None` | 1 per cycle; stalls only with both banks sealed |
| tracker | `None` | `n_tracks + 2` cycles per record, ~3 `n_tracks` cycles per terminator (Kalman: + `cov_width + cov_frac` per assigned track) |
| OS-CFAR | `None` (as CA-CFAR) | 1 per cycle, flush between frames |
| clutter map | fixed (4) | 1 per cycle |
| beamformer | fixed (3) for one beam, `None` otherwise | `n_beams` cycles per sample (joined sinks) |
| monopulse | fixed (2 + CORDIC stages) | 1 per cycle (joined sinks) |
| pulse generator | n/a (source) | 1 per cycle, one bubble per pulse start |
| TVG | fixed (6) | 1 per cycle |

## Host side

`litedsp.radar.design` holds the pure-Python design maths (CFAR alpha from a false-alarm
probability, Kalata tracker gains, steering weights, unit conversions, time-varying-gain
coefficients) and `litedsp.radar.waveform` the chirp helpers shared by the gateware and the
models. The typed drivers (`RangeGateDriver`, `PulseGeneratorDriver`, `CFARDriver`, `OSCFARDriver`,
`ClutterMapDriver`, `TargetListDriver`, `TrackerDriver`, `KalmanTrackerDriver`, `BeamformerDriver`,
`TVGDriver` in `litedsp/software/drivers.py`) wrap the CSR maps; the flow's manifest discovery picks them
by registry key.

## Verification

Every block has a bit-exact integer model in `test/models.py` and a `test/test_<block>.py`
that runs it under random backpressure (`sink_throttle=0.2`, `source_ready_rate=0.7`) plus
functional bounds derived from the design (pulse-compression sidelobes, MTI cancellation,
Doppler bin position and sidelobes, measured CFAR false-alarm rate, centroid error, tracking
RMS error and coasting). All keys are co-simulated with Verilator against the same models
(`sim/run_blocks.py`), including the CA / GO CFAR statistics, the wide 2-D box, the `mac`
pulse compressor, the two-beam beamformer and the two-sink monopulse; the sparse target /
track blocks compute their expected output count from the model. Nightly line coverage is
above 90 % for every key except the composites with nested sub-block arms (pulse compressor,
Doppler processor, monopulse, TVG) and the beamformer's shadow-weight path, which carry
waivers naming their semantic tests.

## Non-goals and composition hints

Staggered PRIs, range migration, space-time adaptive processing and true-time-delay
beamforming are out of scope. Long CPIs that exceed the block RAM can put the corner turn off
chip (DMA the pulse frames out and columns back in) since the Doppler processor only needs
framed columns. The 2-D CFAR replicates its line buffer per read port; for very large maps use
the 1-D CA-CFAR per row (Doppler-only training) or per column after a second corner turn.

## Sonar

Active sonar uses the same chain at audio-like sample rates: `LiteDSPPulseGenerator` drives the
projector (its `tx` strobe blanks the receiver, the framed pulse is the matched-filter reference
through `chirp_reference`), `LiteDSPTVG` compensates the spreading and absorption losses along
the range bins before detection (`tvg_coefficients(40, alpha, g0)` for two-way spherical
spreading plus absorption in dB per bin), and the detectors run on the compressed profile
(`LiteDSPMagnitude` or the log-domain blocks for envelope / log compression, then
`LiteDSPCACFAR` / `LiteDSPOSCFAR` per ping or `LiteDSPClutterMap` across pings). Array
receivers go through `LiteDSPBeamformer` (one stream per hydrophone, weights from
`steering_weights`) or, for two half-arrays, `LiteDSPMonopulse` for a bearing per range bin.
Range bin r is `r * c_s / (2 fs)` (sound speed) and the parameters scale down with the sample
rate: a 100 kHz sonar with 1024 range bins and 16 pings keeps every block at a fraction of the
radar budgets.

## Roadmap

Serial (multiplier-shared) architectures for the OS-CFAR rank filter and the 2-D CFAR line
buffer at large maps, an off-chip corner turn for long CPIs, staggered PRIs and a
detection-list sink for the image overlay block are the next steps; the extended set above
lands the design entries the follow-up families (instrumentation, GNSS) build on.
