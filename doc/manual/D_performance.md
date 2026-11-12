# Performance and resources {#performance}

This appendix gathers the resource, timing and quality numbers of every implementation
configuration (`impl/modules.py`) and of the characterized blocks. Use it to
size a chain and to choose between the architecture options of a block before building. It holds
two kinds of numbers, and neither was measured on a board: see the [status](#intro-status) of
each family.

- **Implementation results** are out-of-context tool results: one block synthesized, and for some
  configurations placed and routed, alone on a device, with its ports as device pins.
- **Quality metrics** (SFDR, ENOB, ripple, settling) are measured on the golden models, which the
  co-simulation holds bit-exact to the generated Verilog ([Verification](#verification)).

The tables of this appendix are generated from the checked-in result files by
`doc/manual/performance.py`; the prose around them is written by hand.

## How the implementation numbers are produced {#perf-conditions}

The implementation flow builds each configuration of `impl/modules.py` (a block, its
parameters and the clock period to constrain), emits its Verilog, and runs the vendor tools on it.
The method and the commands are in [Implementation flows](#ver-impl); the table below gives the
conditions of the recorded results.

| Item | Value |
|------------------------|------------------------------------------------------------------|
| ECP5 | `LFE5UM5G-85F`, CABGA381; OSS CAD Suite 2025-06-25 (Yosys 0.54+23, nextpnr 0.8-35) |
| Artix-7 | `xc7a200tsbg484-3`; Vivado 2025.2, out-of-context synthesis and implementation |
| Artix UltraScale+ | `xcau20p-ffvb676-2-e`; Vivado 2025.2, out-of-context synthesis and implementation |
| Parameters | The factory of each configuration in `impl/modules.py`; 16-bit datapaths |
| Clock constraint | Set by each factory: 10 ns for most, 8 ns to 14.3 ns for a few |
| Resources | LUT / FF / BRAM / DSP after place and route when routed, else after synthesis |
| Raw fmax | `fmax_mhz`: the last recorded route, or the median of a three-route sweep |
| Floor | `fmax_min`: 85 % of the raw fmax, the regression gate |
| Target | `fmax_target`: the 100 MHz engineering objective (95 MHz and 80 MHz for two ECP5 entries) |
| Results file | `impl/budgets.json`, one entry per configuration and device |

An out-of-context result leaves out what a real design adds: the SoC, the clocking, the IO timing
and the neighbours that compete for routing. Treat the raw fmax as an upper bound for the block
inside a design, and the floor as the value the project guarantees not to regress below.

The resource, floor and target gates, and the CI jobs that apply them, are described in
[Implementation flows](#ver-impl); `*` marks the strict target set (`TARGET_CLOSED`).

```sh
# Regenerate the tables of this appendix after a sweep updated impl/budgets.json.
python3 doc/manual/performance.py
# Fail if the tables are stale.
python3 doc/manual/performance.py --check
```

## Timing architecture {#perf-timing-arch}

A block whose datapath only flows forward reaches a higher fmax by adding registers: its latency
grows and its numbers do not change. A block with a loop from one sample to the next cannot do
that. Its new state depends on the previous one in the same clock, so a register in the loop makes
the next sample use a stale value, which changes the arithmetic, the throughput or both.

Each such family therefore gets its timing improvement as an explicit architecture option, a
constructor parameter such as `architecture="pipelined"` or `feedback_delay=2`. The classic
architecture is the API default, except for the CCSDS Reed-Solomon decoder (pipelined by default),
and the implementation registry selects the timing-oriented option. The table below summarizes the recurrence-limited families: raw ECP5 place
and route results, with the 100 MHz objective on the `LFE5UM5G-85F`.

| Family and configuration | Classic ECP5 | Timing option ECP5 | Recurrence that limits timing |
|--------------------------|--------------|--------------------|----------------------------------------------|
| Viterbi hard / soft | 47.4 / 46.5 MHz | 106.0 / 110.8 MHz (RAM survivor) | ACS metric update, global minimum, normalization |
| AGC | 49.6 MHz | 133.9 MHz (two-sample feedback) | Gain multiply, output magnitude, error, gain integration |
| CIC decimator / interpolator | 80.0 / 69.7 MHz | 364.4 / 184.7 MHz (staged) | Cascaded integrator and comb arithmetic |
| CIC parallel x2 / x4 | | 279.5 / 204.2 MHz (staged) | Vector integrators, lane-prefix scans |
| FIR decimator / FIR DDC | 103.5 / 93.6 MHz | 184.9 / 151.4 MHz (operand register) | History and coefficient lookup, multiplier |
| DUC FIR interpolator | 74.3 MHz | 108.2 MHz (operand and product pipeline) | Lookup, multiply, serial accumulator feedback |
| Four-DDC channelizer | 112.7 MHz | 153.1 MHz (FIR operand pipeline) | Replicated DDC reads, bank-wide ready fan-out |
| Resampler farm | 86.3 MHz | 152.8 MHz (operand and product pipeline) | Banked RAM lookup, multiply, accumulator feedback |
| Frame synchronizer, Barker-7 | 79.9 MHz | 132.2 MHz (five-stage retiming) | Matched filter, energy update, threshold product |
| RS decoder (255,223) | 86.5 MHz | 124.3 MHz (scheduled pipeline) | Serial GF multipliers, Forney chain, Chien reductions |
| LMS equalizer, 7 taps | 69.1 MHz | 114.0 MHz (nine-sample delayed update) | FIR rescale, CMA gradient, weight recurrence |
| QPSK receiver IP | 41.7 MHz | 117.6 MHz (delayed carrier and timing loops) | NCO, mixer, detector, PI and timing-error loops |
| SDF FFT | 58.7 MHz | 113.6 MHz (folded), 110.5 MHz (interleaved x2) | Butterfly result into the delay feedback |
| Iterative FFT | 73.6 MHz | 107.6 MHz (registered butterfly) | In-place RAM read, butterfly, write schedule |
| Parallel FFT | 56.9 MHz (split x2) | 122.8 / 107.7 MHz (native P=2 / P=4, pipelined) | Vector feedback line and cascade ready path |
| PFB channel transform, M=16, T=8 | | 113.2 MHz (FFT transform) | Polyphase accumulator, FFT memory schedule |

The values with two or three routes are medians. The timing-option values are the recorded
results of `impl/budgets.json`; the classic values are those recorded in
`doc/timing_architecture.md` when each option landed, and only the FFT, parallel FFT and LMS
classic configurations are still in `impl/budgets.json`. Each family chapter describes its
options: [Filters and rate change](#filters-rate), [Level control and analysis](#level-analysis),
[Communications blocks](#comm), and the [PFB channelizer](#gm-pfb) for the channel transform.

## Implementation results per family {#perf-impl}

One row per configuration of `impl/modules.py`, grouped by the package of its block. The
resources are those of ECP5; AU+ stands for Artix UltraScale+. Each fmax cell gives the raw fmax
in MHz (its floor is 85 % of it): `synth` means the device has a synthesis result only, `not run`
that it was not run on that device. A `*` marks the strict target set. The Artix-7 and Artix UltraScale+ resources are in the per-block datasheets
of the [block catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md)
and in `doc/resources.md`.

<!-- performance.py impl begin: generated, do not edit -->

### Configurations per device {#perf-counts}

| Device | Synthesized | Routed (fmax) | Target set |
|--------------------------|-------------|---------------|------------|
| ECP5 | 205 | 92 | 36 |
| Artix-7 | 98 | 49 | 36 |
| Artix UltraScale+ | 98 | 51 | 36 |

### Generation {#perf-generation}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| cordic_rot | 1943 / 907 / 0 / 2 | 182.2 | synth | synth |
| cordic_vec | 1892 / 899 / 0 / 1 | 196.3 | no fmax | 460.0 |
| nco | 43 / 43 / 2 / 0 | 279.1 | no fmax | 685.9 |
| nco_parallel_x2 | 85 / 52 / 4 / 0 | 272.9 | synth | synth |
| nco_parallel_x4 | 222 / 71 / 8 / 2 | 197.0 | synth | synth |
| nco_qw | 663 / 52 / 0 / 0 | 257.2 | synth | synth |
| pattern_source | 114 / 65 / 0 / 0 | 545.0 | synth | synth |

### Mixing {#perf-mixing}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| channelizer * | 3112 / 1530 / 6 / 24 | 153.1 | 162.9 | 324.1 |
| ddc * | 765 / 395 / 4 / 6 | 151.4 | 156.4 | 331.7 |
| ddc_parallel_x4 | 1919 / 1071 / 8 / 18 | 50.0 | synth | synth |
| duc * | 744 / 417 / 2 / 6 | 108.2 | 120.6 | 244.2 |
| mixer | 380 / 296 / 0 / 4 | 320.6 | no fmax | 729.4 |
| mixer_parallel_x2 | 628 / 334 / 0 / 8 | 312.0 | synth | 657.5 |
| mixer_parallel_x4 | 1252 / 666 / 0 / 16 | synth | synth | synth |
| pfb_channelizer | 1040 / 212 / 0 / 11 | 66.5 | synth | synth |
| pfb_channelizer_fft * | 2477 / 583 / 0 / 14 | 113.2 | 120.1 | 246.2 |
| pfb_channelizer_fft_2x * | 2640 / 584 / 0 / 14 | 105.2 | 129.2 | 227.7 |
| pfb_channelizer_folded * | 1288 / 486 / 0 / 10 | 117.2 | 140.1 | 254.1 |

### Filters {#perf-filter}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| bitstream_decimator | 677 / 240 / 0 / 0 | synth | not run | not run |
| cic_decimator * | 520 / 665 / 0 / 0 | 364.4 | 297.3 | 594.5 |
| cic_interpolator * | 593 / 615 / 0 / 0 | 184.7 | 238.0 | 537.9 |
| cic_parallel_x2 * | 1113 / 832 / 0 / 0 | 279.5 | 274.8 | 478.5 |
| cic_parallel_x4 * | 2770 / 1167 / 0 / 0 | 204.2 | 188.8 | 361.9 |
| dc_blocker | 226 / 97 / 0 / 0 | 237.6 | synth | synth |
| dc_blocker_real | 321 / 89 / 0 / 0 | synth | not run | not run |
| farrow | 808 / 922 / 0 / 16 | 125.1 | synth | 267.3 |
| fir | 2815 / 1555 / 0 / 32 | synth | synth | synth |
| fir_complex | 209 / 106 / 0 / 2 | 211.7 | no fmax | 255.7 |
| fir_decimator | 550 / 217 / 0 / 2 | 184.9 | 207.0 | 368.3 |
| fir_interpolator | 336 / 86 / 0 / 2 | 128.7 | synth | synth |
| fir_parallel_x2 | 5628 / 2611 / 0 / 64 | synth | synth | synth |
| fir_parallel_x4 | 11249 / 4723 / 0 / 128 | synth | synth | synth |
| halfband | 453 / 157 / 0 / 2 | 112.8 | 146.8 | 327.7 |
| iir_biquad | 1722 / 834 / 0 / 24 | 67.3 | no fmax | 188.7 |
| iir_biquad_folded * | 1646 / 1293 / 0 / 24 | 158.2 | 122.5 | 241.4 |
| lms_equalizer | 1773 / 522 / 0 / 56 | 69.1 | synth | synth |
| lms_equalizer_pipelined * | 5179 / 5397 / 0 / 60 | 114.0 | 120.3 | 228.7 |
| moving_average | 238 / 93 / 0 / 0 | 173.8 | synth | synth |

### Rate change {#perf-rate}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| resampler_farm * | 550 / 189 / 2 / 2 | 152.8 | 182.5 | 347.6 |
| resampler_farm_banked | 554 / 214 / 3 / 2 | 132.7 | 171.5 | 385.1 |

### Level control {#perf-level}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| agc * | 390 / 126 / 0 / 4 | 133.9 | 134.9 | 290.1 |
| cfr | 735 / 459 / 0 / 5 | 62.8 | synth | synth |
| cfr_pipelined * | 702 / 724 / 0 / 5 | 106.3 | 179.2 | 296.0 |
| dpd * | 1559 / 634 / 0 / 12 | 109.3 | 104.3 | 212.9 |
| exp2 | 452 / 43 / 1 / 0 | synth | not run | not run |
| gain | 493 / 33 / 0 / 2 | 683.5 | synth | synth |
| log2_lut | 555 / 29 / 0 / 0 | synth | not run | not run |
| power | 959 / 106 / 0 / 2 | 163.3 | synth | synth |
| rms | 1261 / 156 / 0 / 2 | 163.2 | synth | synth |
| saturate | 109 / 33 / 0 / 0 | 481.9 | synth | synth |

### Analysis {#perf-analysis}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| bit_reverse | 141 / 74 / 1 / 0 | synth | not run | not run |
| error_counter | 93 / 64 / 0 / 0 | 449.8 | synth | synth |
| fft | 4387 / 360 / 0 / 28 | 58.7 | no fmax | 143.4 |
| fft_folded * | 4936 / 2674 / 0 / 28 | 113.6 | 110.9 | 180.1 |
| fft_interleaved_x2 * | 9898 / 5350 / 0 / 56 | 110.5 | 112.8 | 193.0 |
| fft_iter * | 1013 / 187 / 2 / 4 | 107.6 | 104.5 | 267.2 |
| fft_parallel_native_x2 * | 9835 / 5287 / 0 / 52 | 122.8 | 111.4 | 193.5 |
| fft_parallel_native_x4 * | 16021 / 8982 / 0 / 94 | 107.7 | 110.3 | 195.3 |
| fft_parallel_native_x4_dsp | 15079 / 8382 / 0 / 74 | 110.5 | 109.1 | 193.2 |
| fft_parallel_x2 | 9163 / 994 / 0 / 56 | 56.9 | 81.0 | 150.7 |
| fft_parallel_x2_folded | 9253 / 4386 / 0 / 56 | synth | 94.6 | synth |
| goertzel | 1375 / 336 / 0 / 17 | 59.5 | synth | synth |
| goertzel_folded * | 954 / 839 / 0 / 17 | 109.1 | 126.9 | 252.1 |
| histogram | 389 / 22 / 0 / 0 | 117.8 | synth | synth |
| magnitude | 157 / 18 / 0 / 0 | 435.0 | synth | synth |
| magnitude_cordic | 1618 / 601 / 0 / 1 | 198.7 | synth | synth |
| psd | 864 / 32 / 0 / 2 | 106.3 | synth | synth |
| stats | 273 / 186 / 0 / 2 | 134.4 | synth | synth |
| window | 391 / 82 / 0 / 2 | 117.6 | synth | 384.3 |

### Communications {#perf-comm}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| am_modulator | 770 / 147 / 0 / 3 | synth | not run | not run |
| bch_decoder | 1329 / 379 / 0 / 0 | synth | not run | not run |
| bch_encoder | 114 / 61 / 0 / 0 | synth | not run | not run |
| block_deinterleaver | 164 / 85 / 2 / 0 | 233.1 | synth | synth |
| block_interleaver | 165 / 85 / 2 / 0 | 234.8 | synth | synth |
| ccsds_rs_decoder * | 3741 / 1482 / 1 / 0 | 121.1 | 138.7 | 247.4 |
| ccsds_rs_encoder | 573 / 265 / 0 / 0 | 262.9 | 261.2 | 620.3 |
| cfo_estimator | 4805 / 1764 / 0 / 4 | 135.3 | synth | synth |
| convolutional_deinterleaver | 468 / 158 / 1 / 0 | synth | not run | not run |
| convolutional_interleaver | 434 / 158 / 1 / 0 | synth | not run | not run |
| correlator | 1050 / 710 / 0 / 14 | 123.9 | synth | synth |
| depuncturer | 31 / 16 / 0 / 0 | 558.0 | synth | synth |
| fm_demod | 1720 / 790 / 0 / 4 | 126.4 | synth | synth |
| fm_modulator | 706 / 91 / 0 / 2 | synth | not run | not run |
| frame_sync * | 990 / 2034 / 0 / 23 | 132.2 | 147.5 | 287.9 |
| fsk_modulator | 1222 / 481 / 0 / 7 | synth | not run | not run |
| gray_demapper | 7 / 11 / 0 / 0 | synth | not run | not run |
| gray_mapper | 7 / 11 / 0 / 0 | synth | not run | not run |
| hamming_decoder | 284 / 141 / 0 / 0 | synth | not run | not run |
| hamming_encoder | 111 / 48 / 0 / 0 | synth | not run | not run |
| hdlc_deframer | 221 / 170 / 0 / 0 | synth | not run | not run |
| hdlc_framer | 188 / 63 / 0 / 0 | synth | not run | not run |
| ldpc_decoder * | 693 / 198 / 2 / 0 | 103.6 | 124.5 | 225.6 |
| ldpc_decoder_lanes_3 * | 1948 / 563 / 6 / 0 | 103.9 | 126.4 | 231.9 |
| ldpc_decoder_lanes_9 * | 4065 / 1376 / 0 / 0 | 98.0 | 124.8 | 227.0 |
| ldpc_decoder_z_parallel * | 10331 / 3553 / 0 / 0 | 108.2 | 130.2 | 189.7 |
| ldpc_encoder | 4719 / 446 / 0 / 0 | 208.7 | synth | synth |
| line_decoder | 43 / 39 / 0 / 0 | synth | not run | not run |
| line_encoder | 12 / 7 / 0 / 0 | synth | not run | not run |
| ofdm_equalizer | 547 / 128 / 0 / 6 | 111.9 | synth | synth |
| pm_modulator | 727 / 91 / 0 / 2 | synth | not run | not run |
| puncturer | 21 / 8 / 0 / 0 | 428.1 | synth | synth |
| rs_decoder * | 3780 / 1466 / 1 / 0 | 124.3 | 143.5 | 270.1 |
| rs_encoder | 487 / 265 / 0 / 0 | 141.6 | synth | synth |
| soft_demapper | 211 / 44 / 0 / 2 | 102.7 | synth | synth |
| ssb_modulator | 1438 / 1230 / 0 / 17 | synth | not run | not run |
| timing_recovery * | 1430 / 561 / 0 / 18 | 113.4 | 127.1 | 236.7 |
| viterbi_decoder * | 6634 / 864 / 2 / 0 | 106.0 | 106.6 | 225.7 |
| viterbi_decoder_acs32 * | 5324 / 1571 / 2 / 0 | 104.3 | 105.2 | 213.2 |
| viterbi_decoder_soft * | 6848 / 864 / 2 / 0 | 110.8 | 105.4 | 213.1 |
| viterbi_decoder_soft_acs32 * | 5554 / 1577 / 2 / 0 | 85.5 | 109.4 | 179.1 |

### Stream utilities {#perf-stream}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| combine | 327 / 33 / 0 / 0 | 331.2 | synth | synth |
| csr_sink | 64 / 64 / 0 / 0 | 339.0 | synth | synth |
| csr_source | 1 / 33 / 0 / 0 | synth | synth | synth |
| framer | 102 / 16 / 0 / 0 | 315.0 | synth | synth |
| iq_pack | 21 / 133 / 0 / 0 | 144.3 | synth | synth |
| iq_unpack | 134 / 2 / 0 / 0 | 1033.1 | synth | synth |
| null_sink | 65 / 32 / 0 / 0 | 359.2 | synth | synth |
| stream_fifo | 32 / 14 / 0 / 0 | 272.7 | synth | synth |
| tdm_demux | 55 / 0 / 0 / 0 | synth | not run | not run |
| tdm_mux | 31 / 1 / 0 / 0 | synth | not run | not run |

### Generated IP cores {#perf-ip}

| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |
|------------------------------------|--------------------|----------|----------|----------|
| ddc_ip * | 4800 / 6866 / 2 / 70 | 107.6 | 121.2 | 274.7 |
| qpsk_receiver_ip * | 2083 / 1000 / 2 / 22 | 117.6 | 132.4 | 237.1 |

### Motor control {#perf-motor}

ECP5 synthesis only.

| Configuration | LUT | FF | BRAM | DSP |
|--------------------------------------|----------|----------|----------|----------|
| angle_ramp | 33 | 33 | 0 | 0 |
| angle_tracker | 677 | 97 | 0 | 0 |
| clarke | 187 | 35 | 0 | 2 |
| dq_controller | 925 | 98 | 0 | 4 |
| dq_controller_decoupling | 1191 | 165 | 0 | 10 |
| foc | 2777 | 760 | 0 | 15 |
| hall_decoder | 379 | 187 | 0 | 0 |
| inverse_clarke | 228 | 51 | 0 | 1 |
| inverse_park | 820 | 189 | 0 | 4 |
| overcurrent_trip | 375 | 36 | 0 | 0 |
| park | 784 | 189 | 0 | 4 |
| pi_controller | 514 | 50 | 0 | 2 |
| pwm | 310 | 223 | 0 | 1 |
| quadrature_decoder | 568 | 140 | 0 | 2 |
| resolver | 5509 | 1825 | 0 | 5 |
| sigma_delta_filter | 2518 | 906 | 0 | 0 |
| sincos | 614 | 23 | 0 | 0 |
| sincos_cordic | 1824 | 924 | 0 | 2 |
| slew_limiter | 141 | 35 | 0 | 0 |
| smo_observer | 2775 | 873 | 0 | 4 |
| svpwm | 611 | 181 | 0 | 1 |

### Audio {#perf-audio}

ECP5 synthesis only.

| Configuration | LUT | FF | BRAM | DSP |
|--------------------------------------|----------|----------|----------|----------|
| audio_eq | 780 | 163 | 0 | 4 |
| chorus | 2431 | 254 | 0 | 2 |
| compressor | 2639 | 390 | 1 | 5 |
| delay_line | 13419 | 236 | 0 | 2 |
| dither | 285 | 133 | 0 | 0 |
| i2s_rx | 81 | 71 | 0 | 0 |
| i2s_tx | 109 | 111 | 0 | 0 |
| lfo | 318 | 58 | 0 | 1 |
| limiter | 2790 | 397 | 2 | 5 |
| loudness | 950 | 426 | 0 | 8 |
| pdm_rx | 1244 | 675 | 0 | 0 |
| peak_meter | 1109 | 188 | 0 | 0 |
| reverb | 33760 | 1439 | 0 | 16 |
| sigma_delta_dac | 582 | 176 | 0 | 0 |
| sigma_delta_mod | 486 | 84 | 0 | 0 |
| stereo_matrix | 617 | 171 | 0 | 2 |
| volume | 375 | 155 | 0 | 4 |
| wet_dry_mix | 227 | 29 | 0 | 4 |

### Radar and sonar {#perf-radar}

ECP5 synthesis only.

| Configuration | LUT | FF | BRAM | DSP |
|--------------------------------------|----------|----------|----------|----------|
| alpha_beta_tracker | 2474 | 981 | 0 | 8 |
| beamformer | 1075 | 678 | 0 | 16 |
| beamformer_4beams | 1478 | 1453 | 0 | 16 |
| ca_cfar | 1266 | 625 | 0 | 2 |
| cfar_2d | 1375 | 723 | 4 | 5 |
| cfar_2d_wide | 1588 | 812 | 4 | 5 |
| clutter_map | 554 | 294 | 0 | 2 |
| corner_turn | 166 | 136 | 4 | 0 |
| doppler | 1768 | 307 | 0 | 14 |
| kalman_tracker | 5884 | 1940 | 0 | 20 |
| monopulse | 1934 | 958 | 0 | 4 |
| mti | 690 | 192 | 2 | 0 |
| os_cfar | 1744 | 445 | 0 | 1 |
| peak_extractor | 1006 | 427 | 0 | 0 |
| pulse_compressor | 4236 | 3018 | 0 | 60 |
| pulse_compressor_mac | 4777 | 4280 | 0 | 16 |
| pulse_generator | 402 | 143 | 2 | 0 |
| range_gate | 363 | 96 | 0 | 0 |
| target_list | 263 | 112 | 0 | 0 |
| tvg | 896 | 374 | 2 | 6 |

### Image {#perf-image}

ECP5 synthesis only.

| Configuration | LUT | FF | BRAM | DSP |
|--------------------------------------|----------|----------|----------|----------|
| alpha_blend | 155 | 28 | 0 | 6 |
| box_overlay | 1145 | 637 | 0 | 0 |
| color_matrix | 742 | 952 | 0 | 9 |
| crop | 342 | 102 | 0 | 0 |
| debayer | 905 | 376 | 2 | 0 |
| downscaler | 339 | 172 | 1 | 0 |
| kernel_2d | 1611 | 676 | 2 | 9 |
| kernel_2d_rgb | 3666 | 1386 | 4 | 27 |
| kernel_5x5 | 3571 | 1575 | 4 | 25 |
| line_buffer | 1340 | 295 | 2 | 0 |
| line_buffer_5x5_rgb | 9104 | 1449 | 8 | 0 |
| pixel_fifo | 695 | 26 | 0 | 0 |
| pixel_from_video | 258 | 89 | 0 | 0 |
| pixel_gain | 158 | 98 | 0 | 3 |
| pixel_histogram | 362 | 160 | 2 | 0 |
| pixel_lut | 148 | 73 | 3 | 0 |
| pixel_pack | 0 | 0 | 0 | 0 |
| pixel_pattern | 538 | 108 | 0 | 0 |
| pixel_stats | 1771 | 1101 | 0 | 0 |
| pixel_to_video | 109 | 94 | 0 | 0 |
| pixel_unpack | 66 | 40 | 0 | 0 |
| rank_filter | 2010 | 559 | 2 | 0 |
| sobel | 1821 | 372 | 2 | 1 |
| threshold | 85 | 13 | 0 | 0 |

<!-- performance.py impl end -->

The two generated cores, `ddc_ip` (NCO, mixer, FIR and decimator) and `qpsk_receiver_ip`, include
the AXI-Stream ports, the AXI-Lite bridge and every register bank, and are routed as one design.

## Application families {#perf-apps}

The motor control, audio, radar and image families are recorded as ECP5 synthesis results only:
no place and route and no Xilinx result is recorded for them. Five of their configurations
(`foc`, `audio_eq`, `compressor`, `doppler`, `cfar_2d`) are listed in the place and route subset of
`impl/modules.py`, but `impl/budgets.json` holds no routed result for them. Their tables are in
[Implementation results per family](#perf-impl) above.

### Motor control and audio notes {#perf-motor-audio}

The AN009 application note uses the FOC, PWM, quadrature decoder, sliding-mode observer, angle
tracker and angle ramp. From the motor table above, their ECP5 synthesis results sum to 7140 LUT,
2126 FF, 0 BRAM and 22 DSP: out-of-context results with default parameters, not a routed design.
The clock budgets of the audio serial engines are in [Two engine styles](#aud-engines).

### Radar and image notes {#perf-radar-image}

The radar and image application notes run configurations close to, but not equal to, the
implementation configurations of `impl/modules.py`. Summed from the tables above, the
implementation configurations of the AN011 chain (range gate, pulse compressor P = 16 classic, MTI,
corner turn, Doppler, 2-D CFAR, peak extractor, target list, alpha-beta tracker) total 12341 LUT,
5992 FF, 10 BRAM and 87 DSP; the pulse compressor alone holds 60 of the DSP. The three blocks of
`examples/image_core.yml` (debayer, pixel gain, colour matrix) total 1805 LUT, 1426 FF, 2 BRAM
and 12 DSP. These are sums of out-of-context ECP5 synthesis results, not a synthesized chain.

## Quality characterization {#perf-quality}

The quality metrics are measured by `char/run_char.py` on the golden models of `test/models.py`;
the CORDIC is measured through a Migen simulation of the block, with the stimulus of
`test_cordic.test_sincos`.
Because the co-simulation holds each model bit-exact to the Verilog, the numbers describe the
gateware. They are *measured on the golden models*, with fixed stimuli, not on a board.

| Block | Configuration and stimulus |
|-------------|---------------------------------------------------------------------------|
| nco | `lut_depth=1024`, `phase_bits=32`, 16-bit; worst case over 7 phase increments, LUT-exact increments for the LUT-exact SFDR |
| cordic | Rotation mode, 16-bit, 16 stages; a 0.92 FS tone rotated through 256 angles |
| mixer | Down-conversion of a 0.76 FS tone at 0.123 with a LUT-exact LO at 1/64; image at the sum |
| fir | `firwin_lowpass(63, 0.2)` in Q1.15; passband up to 0.15, stopband from 0.25 |
| cic | `diff_delay=1`, 16-bit; droop against theory over the output passband, per R and N |
| agc | `mu=8`, `gain_frac=8`, two-sample feedback; constant-envelope tone at 25 % of the target |
| clipper | Clip threshold at half the peak of two tones at 0.101 and 0.117 |
| cfr | `pulse_span=16`, cutoff 0.2; OFDM-like I/Q with about 11 dB PAPR, threshold at 7 dB PAPR |
| dc_blocker | `pole_shift=5`, `precision_bits=8`; 0.95 FS DC step plus a -30 dBFS tone; capped at 140 dB |
| window | Hann, n=64, 16-bit coefficients; sidelobe of the quantized window |

The table below gives each measured value and its gate. The gate is the recorded baseline
(`char/budgets.json`) moved by 3 % of its value, at least 0.01, in the direction of a
regression: a lower SFDR or a higher ripple. The nightly run fails when a measurement crosses it.

<!-- performance.py quality begin: generated, do not edit -->

| Block | Metric | Unit | Measured | Gate |
|-------------|------------------------------|---------|----------|----------|
| agc | Overshoot | % | 0.000 | <= 0.01 |
| agc | Residual level error | % | 0.724 | <= 0.75 |
| agc | Settling time | samples | 30.000 | <= 30.90 |
| cfr | EVM below threshold | % | 1.619 | <= 1.67 |
| cfr | PAPR reduction | dB | 1.567 | >= 1.52 |
| cic | Droop error, R=16, N=3 | dB | 0.000 | <= 0.01 |
| cic | Droop error, R=16, N=4 | dB | 0.000 | <= 0.01 |
| cic | Droop error, R=4, N=3 | dB | 0.000 | <= 0.01 |
| cic | Droop error, R=4, N=4 | dB | 0.000 | <= 0.01 |
| cic | Droop error, R=8, N=3 | dB | 0.000 | <= 0.01 |
| cic | Droop error, R=8, N=4 | dB | 0.000 | <= 0.01 |
| clipper | IMD3 | dBc | 15.452 | >= 14.99 |
| cordic | ENOB | bits | 12.705 | >= 12.32 |
| dc_blocker | DC rejection | dB | 140.000 | >= 135.80 |
| fir | Passband ripple | dB | 0.019 | <= 0.03 |
| fir | Stopband attenuation | dB | 54.973 | >= 53.32 |
| mixer | Image rejection | dB | 117.560 | >= 114.03 |
| nco | ENOB | bits | 8.850 | >= 8.58 |
| nco | Noise floor | dBFS | -52.025 | <= -50.46 |
| nco | SFDR, LUT-exact increments | dB | 103.473 | >= 100.37 |
| nco | SFDR, swept increments | dB | 58.611 | >= 56.85 |
| window | Peak sidelobe attenuation | dB | 31.471 | >= 30.53 |

<!-- performance.py quality end -->

```sh
# Measure every block, print the table and apply the gate.
python3 char/run_char.py
# After a deliberate quality change: record the new baseline and the report.
python3 char/run_char.py --update --report
```
