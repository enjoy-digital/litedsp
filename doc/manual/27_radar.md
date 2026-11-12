# Radar and sonar blocks {#radar}

The radar family adds pulse-Doppler radar and active-sonar processing to LiteDSP: pulse timing,
matched-filter pulse compression, clutter cancellation, the corner turn, Doppler processing, CFAR
detection in one and two dimensions, peak extraction with sub-bin centroids, per-CPI target lists,
multi-target tracking, beamforming and sonar time-varying gain. This chapter is for the engineer
who assembles a radar or sonar receiver from these blocks.

The concepts are explained in [Radar and sonar in a nutshell](#radar-primer). The blocks follow
the common contract of [Block contract](#architecture): Q1.15 I/Q samples, elastic ready/valid
streams, bit-exact NumPy golden models. This chapter adds what is specific to the family: the
radar stream kinds, their framing rules and the units.

## At a glance {#rad-glance}

| Item | Value |
|------------------------|------------------------------------------------------------------|
| Directory | `litedsp/radar/` (16 files) |
| Blocks | 17 registry entries, category `radar`, plus `bit_reverse` (analysis) |
| Stream layouts | `iq_layout`, `real_layout`, `cell_layout`, `target_layout`, `track_layout`, `angle_layout` |
| Host helpers | `litedsp.radar.design`, `litedsp.radar.waveform` |
| Drivers | 10 typed drivers in `litedsp/software/drivers.py` |
| Examples | `examples/chirp_radar.py` (AN004), `examples/pulse_doppler_radar.py` (AN011) |
| Status | See [status](#intro-status) |
| Registers | See [Radar registers](#reg-radar) |

Each block also has a generated datasheet in the online catalogue
([index](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md)), with its
parameters, ports, registers and verification.

## The processing chain {#rad-chain}

A pulse-Doppler receiver is a chain of two halves. The front end works on each pulse as it
arrives, in fast time; the corner turn hands range-bin columns to the detection half, which works
on the range-Doppler map and ends with sparse records once per CPI. The figure below shows the
front end.

![Radar front end. The range gate frames each receive window as one pulse; the pulse compressor
and the MTI canceller keep that framing; the corner turn turns a CPI into slow-time columns for
the Doppler processor.](rad_front.svg)

The figure below shows the detection half. The labels on the arrows are the stream kinds of
[Stream kinds and framing](#rad-streams).

![Radar detection. The Doppler processor produces map rows of non-negative cells; the 2-D CFAR
adds a threshold and a decision to each cell; the peak extractor turns detected peaks into one
target burst per CPI, read by the host through the target list or filtered into tracks by the
tracker, both fed through a split.](rad_detect.svg)

Sonar uses the same chain at a lower sample rate, with a pulse generator in front and a
time-varying gain before detection ([Sonar](#rad-sonar)).

## Stream kinds and framing {#rad-streams}

The radar blocks exchange six kinds of streams. Each kind has a layout from `litedsp/common.py`
and a framing rule, given by `first` and `last`, as the table below shows.

| Kind | Layout | One frame is | Between |
|---------|---------------------------|--------------------------------------|--------------------------|
| Fast time | `iq_layout` | One pulse, range bin 0 to N-1 | Range gate to corner turn |
| Slow time | `iq_layout` | One range bin, M pulses | Corner turn to Doppler |
| Map | `real_layout(dw)` | One range bin, M Doppler bins, natural order | Doppler to CFAR |
| Cell | `cell_layout(dw)` | Same framing as its input | CFAR to peak extractor |
| Target | `target_layout` | One burst per CPI | Peak extractor onwards |
| Track | `track_layout` | One burst per CPI | Tracker output |

A *cell* carries the value `data` (a magnitude or a power, unsigned), the `threshold` the detector
computed for it and the `detect` decision.

A *target* record carries the sub-bin `range` and `doppler` (unsigned, `frac_bits` fractional bits),
the peak value `data` and `hit`. A *track* record carries `range`, `doppler`, a signed `velocity` in
bins per CPI, the track `id`, its `hits` count and `hit`.

Target and track streams are *bursts*: one per CPI, the records followed by one terminator beat,
as the figure below shows.

![Target bursts. A CPI with three targets sends three records with hit = 1, then a terminator
with hit = 0 whose data field is the record count and which carries last. An empty CPI is a
single terminator with first and last.](rad_burst.svg)

The terminator of a track burst has its `hits` field set to the number of active tracks. The
interrupts of the peak extractor (`ev.cpi`), the target list (`ev.list`) and the trackers
(`ev.update`) fire with the terminators; the `ev.cpi` of the range gate fires at the start of
each CPI.

Four rules hold for the whole family.

- **Counting from reset.** The window, the FFT, the Doppler processor, the 2-D CFAR, the peak
  extractor and the corner turn count beats and rows from reset. The last four check `first` and
  `last` against their counters; a mismatch sets the sticky `frame_error`, cleared by `clear`.
  The 1-D CFARs restart their window on each `first`. Keep the whole chain in one reset domain
  and start the source cleanly.
- **Zero padding and flush.** The windowed blocks (CA-CFAR, OS-CFAR, 2-D CFAR, peak extractor)
  pad the frame edges with zeros. After `last` they push the trailing cells out with flush beats,
  with `sink.ready` low, so the output has one beat per input cell with the same framing.
- **Edge cells.** The padded edges, and an MTI notch column, see small training sums. Set the
  runtime `threshold_min` floor a few times above the noise level.
- **Compressor alignment.** The pulse compressor delays `first` and `last` by `P - 1` beats, so
  range bin `r` of pulse `p` leaves at position `r` of output frame `p`. The first `P - 1`
  positions of a frame hold the tail of the previous pulse; gate them out or ignore them.

## Units {#rad-units}

The blocks work in bins and fixed-point words; the host converts. The table below gives each
quantity, its representation and the helper of `litedsp.radar.design` or
`litedsp.radar.waveform` that converts it.

| Quantity | Representation | Host conversion |
|----------------|------------------------------------------|------------------------------------------|
| Range bin | Integer, or Q.`frac_bits` after interpolation | `range_bin_metres` |
| Doppler bin | 0 to M-1, `k >= M/2` negative | `doppler_bin_velocity` |
| Velocity | Signed Q.`velocity_frac` bins per CPI | Times the bin size per CPI |
| CFAR `alpha` | Unsigned, `threshold_frac` fractional bits | `cfar_alpha` |
| Tracker gains | Unsigned Q1.`gain_frac` | `alpha_beta_from_index` |
| Chirp | Start and rate frequency words | `chirp_words` |
| TVG law | Q.`gain_frac` log2 words | `tvg_coefficients` |

The `domain` of `cfar_alpha(pfa, n_train_cells, domain)` is `power` for `i^2 + q^2` cells and
`magnitude` for magnitude cells. `tracker_gains(alpha, beta)` quantizes a gain pair, from
`alpha_beta_from_index` or chosen by hand, to the tracker words. `chirp_reference` reproduces
the samples of `LiteDSPChirp` bit for bit, so a matched filter built from it is matched to the
gateware pulse.

Cells are wider than samples: `data_width + 1` bits from the alpha-max-beta-min magnitude,
`2 * data_width + 1` bits from the power. The detection blocks therefore default to
`data_width=17`. The flow injects the chain `data_width` into every block that has one, so a
chain of 16-bit I/Q and 17-bit cells sets `data_width` per block in the netlist.

## Timing and waveforms {#rad-timing}

The range gate turns a continuous I/Q stream into framed pulses (`LiteDSPRangeGate`). A counter
advances on every accepted input sample, so the timing is exact under any ready/valid pattern.

It counts the PRI, passes the samples of the receive gate framed as one pulse, and drops the others.
Its outputs `tx`, `rx_gate` and `cpi_start` mark the transmit pulse, the receive window and the
start of each CPI.

| Parameter | Default | Meaning |
|----------------|---------|--------------------------------------------------------|
| `n_range_bins` | 64 | Maximum gate length, sizes the runtime gate length |
| `n_pulses` | 16 | Pulses per CPI (reset value) |
| `pri` | 128 | PRI in samples (reset value) |
| `gate_start` | 0 | Gate start in samples (reset value) |
| `pulse_width` | 16 | Length of the `tx` strobe (reset value) |

The gate runs continuously when enabled, or for exactly one CPI per trigger in single mode. The
output rate is the gate length over the PRI.

The pulse generator is the transmit side (`LiteDSPPulseGenerator`). It frames a linear-FM chirp
of `pulse_len` samples and pads it with zeros up to the PRI; `pulse_len`, `pri` and `n_pulses`
are runtime registers. An internal `LiteDSPChirp` restarts from its start and rate words at each
pulse, which costs one idle beat per pulse start.

## Pulse compression {#rad-compression}

The pulse compressor is the matched filter of the chirp of `LiteDSPChirp`
(`LiteDSPPulseCompressor`). It computes its own reference from `pulse_len` and `bandwidth` (in
cycles per sample) with `pulse_compressor_taps`, optionally tapered by `window`. The figure below
shows its structure.

![Pulse compressor. Two complex FIRs with real taps run in lock step, one with the real part of
the reference, one with the imaginary part; the recombiner forms the complex result and
saturates it. The frame tags travel beside the filters, delayed by P-1 beats.](rad_compressor.svg)

The two FIRs are `LiteDSPFIRFilterComplex` instances ([Filters and rate
change](#filters-rate)). The recombiner computes `y = (re.i - im.q) + j (re.q + im.i)` with
saturation. The default `shift`, `data_width - 1 + ceil(log2(pulse_len))`, makes a full-scale echo
peak near full scale.

| Parameter | Default | Meaning |
|----------------------------|------------|------------------------------------------------------------|
| `pulse_len` | 16 | Pulse length P in samples |
| `bandwidth` | 0.5 | Chirp sweep in cycles per sample |
| `window` | `rect` | Reference taper: `rect`, `hann`, `hamming`, `blackman` |
| `shift` | None | Output rescale, None for the default above |
| `fir_architecture` | `classic` | `classic`, `pipelined` or `mac` (shared multipliers, `n_macs` per FIR) |

The classic architecture spends `4 P` real multipliers, one per tap of each FIR on I and Q. The
`mac` architecture shares `n_macs` multipliers per FIR and takes `P / n_macs` cycles per sample,
which suits long pulses at low sample rates; its latency is then `None`.

The unit test checks a PSLR of at least 10 dB for the rectangular reference at P = 16 and at least
15 dB for the Hamming reference at P = 32.

## Clutter cancellation {#rad-clutter}

The MTI canceller subtracts the previous pulses range bin by range bin (`LiteDSPMTICanceller`). It
keeps `order - 1` previous pulses in RAMs indexed by a range counter that `first` restarts.

The runtime `mode` selects the two-pulse canceller (0) or the three-pulse one (1, needs `order=3`).
The output is rescaled by `shift`, by default the log2 of the canceller's peak gain (1 for two
pulses, 2 for three), so it never saturates;
`bypass` passes pulses unchanged.

The clutter map detects across scans instead (`LiteDSPClutterMap`). It keeps one exponential average
per cell in a RAM and detects a cell that exceeds `alpha` times its own average, floored at
`threshold_min`.

A detected cell does not update its average, unless `learn_all` is set; `freeze` stops learning. The
scan after reset or `clear` initializes the averages without detecting, so every scan must cover
every cell.

## Corner turn and Doppler {#rad-doppler}

The corner turn writes `n_pulses` framed pulses of `n_range_bins` beats and reads them back as
`n_range_bins` columns of `n_pulses` beats (`LiteDSPCornerTurn`).

It reuses the block-transpose engine of the interleavers with a ping-pong RAM of two CPIs, so the
throughput is one sample per cycle once the first CPI has filled. Beats before the first `first` are
dropped, which absorbs the pipeline fill of the compressor.

The Doppler processor turns slow-time columns into map rows (`LiteDSPDopplerProcessor`). It is a
composite of `LiteDSPWindow` (omitted for `rect`), a scaled radix-2 `LiteDSPFFT`, a magnitude
stage and `LiteDSPBitReverse` ([Level control and analysis](#level-analysis)). Each output frame
holds the `n_pulses` Doppler bins of one range bin in natural FFT order.

| Parameter | Default | Meaning |
|---------------|----------|-----------------------------------------------------------|
| `n_pulses` | 16 | FFT size M |
| `window` | `hann` | `rect`, `hann`, `hamming`, `blackman` |
| `magnitude` | `approx` | `approx` (alpha-max-beta-min, `dw + 1` bits) or `power` (`2 dw + 1` bits) |

The SDF FFT releases the tail of a column only as the next column arrives. A live chain never
stops, so this needs no care; a simulation that ends after one CPI must feed one more column.
The unit test checks Hann sidelobes at or below -25 dB.

## Detection {#rad-detection}

Three CFAR detectors produce cell streams. All compute `threshold = alpha x noise estimate`,
rounded and floored at the runtime `threshold_min`, and set `detect` when the cell exceeds it.
`alpha` is unsigned with `threshold_frac` fractional bits (8 by default); it resets to 2.0 on
the CA and 2-D detectors and to 4.0 on the OS detector.

| Block | Noise estimate | Defaults |
|------------------------|----------------------------------------|------------------------------------|
| `LiteDSPCACFAR` | CA, GO or SO, runtime `mode` | `n_train=8`, `n_guard=2` |
| `LiteDSPOSCFAR` | Ranked training cell, runtime `rank` | `n_train=4`, `n_guard=2` |
| `LiteDSPCFAR2D` | Mean of the box minus the guard box | `n_train=(4, 2)`, `n_guard=(1, 1)` |

The 1-D detectors run along each frame, a range profile or a map row, with a window of
`2 (n_train + n_guard) + 1` cells. The OS-CFAR finds the rank
in parallel with `(2 n_train)^2` comparators and supports `n_train` up to 8; its rank resets to
the usual three-quarter quantile.

The 2-D CFAR sees the map as `n_range_bins` rows of `n_doppler_bins` cells, the order of the Doppler
processor. `R` and `C` are the training plus guard sizes in rows and cells.

The last `2R + 1` rows live in a line buffer with four read ports, which synthesis replicates;
column sums live in two small RAMs. `C` flush cells per row bring the throughput to `M / (M + C)`,
plus `R` flush rows per CPI.

`n_training`, the number of training cells, is what `cfar_alpha` needs. The `CFARDriver` reads
it from the `config` register, so `set_pfa(pfa, domain)` needs no other argument. Its
`set_mode()` is for the CA-CFAR only: the 2-D CFAR has no mode, and the driver raises a
`ValueError` on it.

## Peaks and target lists {#rad-peaks}

The peak extractor turns detected cells into target records (`LiteDSPPeakExtractor`). Two line
buffers give each cell its 3 x 3 neighbourhood, zero padded. A detected cell becomes a record
when it is a strict maximum over its earlier neighbours and no smaller than the later ones, so a
plateau gives exactly one record.

With interpolation on, a bit-serial divider computes the parabolic offset along each axis in
`frac_bits + 3` cycles per record, with the input stalled. The offset is clamped to +/-0.5 bin
and is 0 where the curvature is not negative. The output is one target burst per CPI, with the
optional `ev.cpi` interrupt.

The target list buffers each CPI's burst for the host (`LiteDSPTargetList`). Its ping-pong RAM
holds `2 x max_targets` records (16 by default). A terminator seals a bank, and the sealed list
is re-emitted framed while the other bank fills. Records beyond `max_targets` are dropped,
counted and flagged by the sticky `overflow`.

The host reads the last sealed list through `index`, `range`, `doppler`, `data` and `count`. A
list stays readable until the next CPI's terminator, so the host has one CPI to read it. The
input stalls only when both banks are sealed.

## Tracking {#rad-tracking}

Two trackers share one engine: register file, association, confirmation and the track burst.
They differ in the filter update.

| Block | Update | Extra cost |
|----------------------------------------|--------------------------------|----------------------------|
| `LiteDSPAlphaBetaTracker` | Fixed gains `alpha`, `beta` (Q1.`gain_frac`) | None |
| `LiteDSPKalmanTracker` | Constant-velocity Kalman per axis | Bit-serial gain division per track |

Each record is associated serially with the active, unassigned track whose prediction lies
within the gates, the one with the smallest `|dr| + |dd|` first. A record with no track starts a
tentative track in the lowest free slot, or is dropped when none is free. This costs
`n_tracks + 2` cycles per record, with the input stalled.

The terminator updates every active track. An assigned track filters its position and velocity
and counts a hit; it is confirmed at `confirm_hits` hits. An unassigned track coasts on its
prediction and is freed after `max_misses` misses in a row. The confirmed tracks, and the
tentative ones with `emit_tentative`, leave as a track burst.

The Kalman tracker keeps a covariance per track and axis, clamped to `cov_width` bits with the
sticky `cov_sat`. For a tracking index `lam = sqrt(q / r)`, its steady-state gains approach
`alpha_beta_from_index(lam)`. Its update adds `cov_width + cov_frac` cycles per assigned track.

## Arrays {#rad-arrays}

The beamformer forms `n_beams` beams from `n_elements` joined I/Q streams
(`LiteDSPBeamformer`). Each beam is `sum_e w[e] x[e]` with complex weights in signed
Q2.`weight_frac`. With more than one beam, the beams leave one per cycle with a `channel` tag,
so the block takes `n_beams` cycles per sample.

The host writes the weights into a shadow set: `weight_index` selects the entry (`beam x
n_elements + element`), and a write of `weight` (fields `re` and `im`) loads it; `commit` copies
the set between two samples, so a beam never mixes old and new weights. The reset weights average
the elements, which points the beam at broadside. The `weight` register places `re` at bit 0 and
`im` at bit `max(16, weight_width)`; the `config` register reports `weight_width` in bits 24 to
29, and `BeamformerDriver.set_weights()` packs the weights with it.

The monopulse block gives the phase of `a * conj(b)` for two joined streams
(`LiteDSPMonopulse`). A mixer forms the product and a vectoring CORDIC gives its angle on
`angle_layout`. The host converts the phase to an angle of arrival with the spacing and the
wavelength.

## Sonar {#rad-sonar}

Active sonar uses the radar chain at low sample rates. The pulse generator drives the projector:
its `tx` strobe blanks the receiver, and `chirp_reference` gives the matched-filter reference.
The time-varying gain compensates spreading and absorption along the range bins before
detection.

The TVG computes its gain in the log2 domain, `g(r) = g0 + k_log log2(r) + k_lin r`, with `log2(r)`
from a ROM (`LiteDSPTVG`). `LiteDSPExp2` turns it into a linear gain, applied with saturation and
the sticky `saturated` flag.

The sample travels in a delay branch of the same latency, so `bypass` is exact.
`tvg_coefficients(40, alpha, g0)` gives two-way spherical spreading plus absorption.

Detection then runs on the compressed profile with `LiteDSPMagnitude` or the log-domain blocks,
followed by `LiteDSPCACFAR` or `LiteDSPOSCFAR` per ping, or `LiteDSPClutterMap` across pings.
Array receivers use the beamformer, one stream per hydrophone, or the monopulse block for a
bearing per range bin. The range bin is `c_s / (2 fs)` with the speed of sound `c_s`.

## Block summary {#rad-blocks}

The table below lists every block of the family with its registry key, its declared latency and
its throughput; the source files are under `litedsp/radar/`. Most radar blocks buffer a frame, a
column or a CPI, so their latency is data dependent (`None`) and the flow cannot balance them
automatically.

| Block (key) | Latency | Throughput |
| ---------------------------------------- | ---------------------------- | -------------------------------- |
| `LiteDSPRangeGate` (`range_gate`) | 1 | 1 sample per cycle, gate / PRI out |
| `LiteDSPPulseGenerator` (`pulse_generator`) | Source | 1 per cycle, one idle beat per pulse |
| `LiteDSPPulseCompressor` (`pulse_compressor`) | FIR latency + 1 (4 by default); None with `mac` | 1 per cycle; `P / n_macs` cycles with `mac` |
| `LiteDSPMTICanceller` (`mti`) | 2 | 1 per cycle |
| `LiteDSPCornerTurn` (`corner_turn`) | None (a CPI) | 1 per cycle after the fill |
| `LiteDSPDopplerProcessor` (`doppler`) | None (a column) | 1 per cycle after the fill |
| `LiteDSPCACFAR` (`ca_cfar`) | None (nominal `T + G + 4`) | 1 per cycle, `T + G + 1` flush beats per frame |
| `LiteDSPOSCFAR` (`os_cfar`) | None (nominal `T + G + 4`) | As the CA-CFAR |
| `LiteDSPCFAR2D` (`cfar_2d`) | None | `M / (M + C)`, plus `R` flush rows per CPI |
| `LiteDSPClutterMap` (`clutter_map`) | 4 | 1 per cycle |
| `LiteDSPPeakExtractor` (`peak_extractor`) | None | 1 per cycle, `frac_bits + 3` per record, one flush cell per row and one flush row per CPI |
| `LiteDSPTargetList` (`target_list`) | None | 1 per cycle, stalls with both banks sealed |
| `LiteDSPAlphaBetaTracker` (`alpha_beta_tracker`) | None | `n_tracks + 2` cycles per record |
| `LiteDSPKalmanTracker` (`kalman_tracker`) | None | As the alpha-beta tracker |
| `LiteDSPBeamformer` (`beamformer`) | 3 with one beam, None otherwise | `n_beams` cycles per sample |
| `LiteDSPMonopulse` (`monopulse`) | 2 + CORDIC latency (21 by default) | 1 per cycle |
| `LiteDSPTVG` (`tvg`) | 6 | 1 per cycle |

`LiteDSPBitReverse` (`bit_reverse`, in `litedsp/analysis/`) reorders an N-beat frame from
bit-reversed to natural order and skips the fill beats of the SDF FFT; the Doppler processor uses
it.

## Resources and memory {#rad-resources}

The family is synthesized on ECP5 only (see [status](#intro-status)); the out-of-context results per
block are in [Radar and sonar results](#perf-radar). Memory grows with the geometry: the corner turn
holds `2 x N x M` samples of `2 dw` bits, and the 2-D CFAR line buffer holds `(2R + 1) x M` cells,
replicated per read port.

The pulse compressor dominates a chain: its classic architecture spends `4 P` multipliers. For
long pulses, the `mac` architecture trades multipliers for cycles, and `LiteDSPCorrelator` is the
packaged matched filter for real (PN, Barker) references.

## Host side {#rad-host}

`litedsp.radar.design` holds the host maths in pure Python: CFAR `alpha`, tracker gains, steering
weights, unit conversions and TVG words. `litedsp.radar.waveform` holds the chirp helpers that the
gateware and the models share. The table below lists the typed drivers of
`litedsp/software/drivers.py`.

| Driver | Block | Main methods |
|-----------------------------------|-------------------------|----------------------------------------|
| `RangeGateDriver` | Range gate | `set_pri`, `set_gate`, `set_pulse`, `start`, `trigger` |
| `PulseGeneratorDriver` | Pulse generator | `set_waveform`, `start_train`, `single`, `stop` |
| `CFARDriver` | CA-CFAR, 2-D CFAR | `set_pfa`, `set_alpha`, `set_floor`; `set_mode` (CA-CFAR only) |
| `OSCFARDriver` | OS-CFAR | `set_rank`, `set_alpha`, `set_floor` |
| `ClutterMapDriver` | Clutter map | `set_alpha`, `set_floor`, `set_learning`, `clear` |
| `TargetListDriver` | Target list | `read_targets`, `overflow`, `clear` |
| `TrackerDriver` | Alpha-beta tracker | `set_tracking_index`, `set_gates`, `set_confirm` |
| `KalmanTrackerDriver` | Kalman tracker | `set_noise`, `set_tracking_index`, `cov_sat` |
| `BeamformerDriver` | Beamformer | `set_steering`, `set_weights`, `commit` |
| `TVGDriver` | TVG | `set_law`, `set_bypass`, `saturated` |

The methods work in physical units. `RangeGateDriver.set_pri` takes seconds, with the sample rate
as `clk_freq`; `PulseGeneratorDriver.set_waveform` takes the bandwidth in Hz and the pulse and
PRI in seconds; `BeamformerDriver.set_steering` takes a beam, an angle in degrees, the spacing
in wavelengths and a taper; `TVGDriver.set_law` takes the law in dB.

A driver binds to the registers of one block instance by its prefix, the name of the block in the
SoC, through any bus object that exposes `bus.regs`, such as a LiteX `RemoteClient` ([Host
drivers](#apps-drivers) shows the pattern).

`set_pfa` is not available on the OS-CFAR, whose `alpha` depends on the rank: use `set_alpha`.
`discover()` of the same module finds the drivers of a whole register map; see [Flow, generator,
GUI and host software](#tooling).

## Verification {#rad-verification}

Every block has a bit-exact integer model in `test/models.py` and a unit test that runs it under
random backpressure, plus functional bounds derived from the design: pulse-compression
sidelobes, MTI cancellation, Doppler bin position and sidelobes, measured CFAR false alarm rate,
centroid error, tracking RMS error and coasting. The method is in
[Verification](#verification).

All 17 keys are co-simulated with Verilator against the same models (`sim/run_blocks.py`),
including the CA and GO statistics, the wide 2-D box, the `mac` compressor, the two-beam
beamformer and the two-sink monopulse. The sparse target and track blocks compute their expected
output count from the model.

Nightly line coverage is above 90 % for every key, except the composites with nested sub-blocks
(pulse compressor, Doppler processor, monopulse, TVG) and the beamformer's shadow-weight path.
These carry waivers in `sim/coverage_waivers.json` that name their semantic tests.

## Application note: chirp pulse compression {#rad-an004}

`examples/chirp_radar.py` (AN004) demonstrates pulse-compression ranging with general-purpose
blocks rather than the packaged compressor. `LiteDSPChirp` produces a linear-FM pulse; a NumPy
channel echoes it from three targets with delay, attenuation and noise; two
`LiteDSPFIRFilterComplex` and a recombiner form the matched filter; `LiteDSPMagnitude` gives the
envelope. The peaks of the envelope are the target ranges.

The reference is the pulse captured from the simulated `LiteDSPChirp`, with its LUT and
phase-accumulator quantization, so the filter is matched to what the gateware sends. The
configuration is a 48-sample pulse, 16-bit I/Q, targets at delays 60, 200 and 205 samples with
amplitudes 0.7, 0.5 and 0.4, and two chirp bandwidths, `fs/2` and `fs/8`.

A target at delay `d` peaks at output sample `d + P - 1`, the full-overlap lag of the
correlation. The declared latencies of the blocks are pipeline fill in cycles, absorbed by their
valid pipelines; they add no sample-index offset. The script recovers every delay exactly from
this arithmetic.

```sh
python3 examples/chirp_radar.py --plot-dir /tmp/an004
```

```console
Chirp radar: P=48-sample LFM pulse, targets (delay, a) = [(60, 0.7), (200, 0.5), (205, 0.4)]
  wide   B=0.500 fs (BT=24.0): peaks at [60, 200, 205] (true [60, 200, 205]), -3 dB width 1.65 samples (theory ~1.77), PSLR 13.6 dB
  narrow B=0.125 fs (BT= 6.0): peaks at [60, 202] (true [60, 200, 205]), -3 dB width 6.95 samples (theory ~7.09), PSLR 16.9 dB
  PASS: all wideband delays exact, close pair resolved only at high B, resolution x4.2 with 4x bandwidth, PSLR 13.6 dB
  plots -> /tmp/an004/an004_compression.png, /tmp/an004/an004_resolution.png
```

With the wide chirp, every delay is recovered exactly and the 5-sample pair is resolved. With the
narrow chirp, the pair falls inside the `0.886 / B` resolution cell of about 7 samples and merges
into one return.

The width of the main lobe scales with the bandwidth, and the measured PSLR is close to the 13.2 dB
of an unweighted chirp; the script gates it at 10 dB.

![AN004 compressed pulses (simulation). Top: wide chirp, three sharp returns with the 200/205
pair resolved. Bottom: narrow chirp, the pair fuses into one broad return. The example also writes
a zoom on the pair, `an004_resolution.png`.](rad_an004_compression.png)

The example's 48-tap matched filter instantiates `4 x 48` multipliers; a taper on the reference
lowers the sidelobes at the cost of the main lobe width.

## Application note: pulse-Doppler radar {#rad-an011}

`examples/pulse_doppler_radar.py` (AN011) assembles the family into a complete pulse-Doppler
processor and runs it on a synthetic scene. Every block is the real gateware in a Migen
simulation. The chain is the one of [The processing chain](#rad-chain) with these parameters.

| Block | Configuration |
|------------------|---------------------------------------------------|
| Range gate | PRI 80 samples, N = 64 range bins, M = 16 pulses |
| Pulse compressor | P = 16, bandwidth 0.5, Hamming |
| MTI | Three-pulse |
| Doppler | Hann, 16-point FFT, `approx` magnitude |
| 2-D CFAR | `n_train=(3, 2)`, `n_guard=(1, 1)`, 54 training cells |
| Target list | 16 records |
| Tracker | Alpha-beta, 8 slots |

The scene has three moving targets, one stationary clutter return and Gaussian noise of 200 LSB.

| Target | Range bin | Doppler bin | Amplitude | Motion per CPI |
|---------|-----------|-------------|-----------|-------------------------------|
| 0 | 12 | 3.0 | 0.5 | +0.5 range, +0.2 Doppler |
| 1 | 30 | 11.0 (-5) | 0.3 | -0.5 range, +0.1 Doppler |
| 2 | 45 | 6.4 | 0.2 | +0.1 range, +0.05 Doppler |
| Clutter | 20 | 0 | 0.8 | Stationary |

The script runs the chain in three passes that hand their captured streams to the next one. The
front end processes two CPIs and one PRI of ADC samples.

The detection pass feeds the front-end columns, plus one flush column for the FFT, to the Doppler
processor, the CFAR, the peak extractor and the target list. The tracking pass feeds the tracker
with the detected bursts and 22 synthesized CPIs.

The CFAR `alpha` is `cfar_alpha(1e-4, 54, "magnitude")`. Its `threshold_min` floor of 40 LSB
keeps the zero-padded first and last rows and the MTI notch column from detecting noise.

```sh
python3 examples/pulse_doppler_radar.py --plot-dir /tmp/an011
```

```console
[pass 1] framing ok, compressed peaks [12, 20, 30, 45] (expected [12, 20, 30, 45]), MTI clutter suppression 34.1 dB
[...]
[pass 2] targets found per CPI [3, 3] / 3, sidelobe detections [1, 0], false alarms [0, 0], max range / Doppler error 0.19 / 0.10 bin, clutter cell detected: 0
         CPI 0 unmatched records (range, Doppler, cell): [(23.06, 10.94, 159)]; targets [(12.0, 3.0), (30.0, 11.0), (45.0, 6.4)]
[...]
[pass 3] confirmed tracks [0, 2, 3] (targets 3), range RMS over CPIs 8..23 0.05 bin, max range-rate error 0.004 bin/CPI
[...]
  plot -> /tmp/an011/an011_pulse_doppler.png
  PASS: front end, detection and tracking gates met
```


The compressed peaks land exactly on the target ranges (the compressor re-aligns the frame tags
by `P - 1`), and the three-pulse MTI takes the stationary return down by 34 dB.

The peak extractor recovers the 6.4-bin Doppler to 0.10 bin and the ranges to 0.19 bin; the
compressed peak is not a parabola, so the range centroid has a small bias.

The one unmatched record of CPI 0 is a compression sidelobe of target 1, the strongest return after
the MTI, seven bins away in range at the same Doppler. The tracker gates reject it.

The tracks confirm at CPI 2, keep their ids through the range crossing and the dropped
detections, and settle to 0.05 bin RMS.

![AN011 results (simulation). Left: range profile of pulse 5 before and after the MTI, the
clutter at bin 20 drops into the noise. Middle: the CPI-0 range-Doppler map with the CFAR
detections, the centroids and the truth. Right: the three tracks against the truth over 24
CPIs.](rad_an011_pulse_doppler.png)

The example simplifies the scene: integer target ranges per CPI, no range migration, no
transmit blanking, a single PRF and a synthesized detection stream for the long tracking pass.

## Limits {#rad-limits}

Staggered PRIs, range migration, space-time adaptive processing and true-time-delay beamforming are
out of scope. A long CPI can put the corner turn off chip, through DMA to memory.

Where to go next: [Radar and sonar primer](#radar-primer), [Using the application families](#apps-using), [Radar
registers](#reg-radar).
