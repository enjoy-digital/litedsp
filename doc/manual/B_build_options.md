# Build options {#build-options}

This appendix lists the options of the tools of the project: the command lines of the four
tools, the keys of the generator YAML files and of the flow netlists, the options of the benches
and their host scripts, and the constructor parameters of every block of the registry. The
chapters explain when to use them; this appendix gives their names and defaults.

## Generator command line {#opt-gen-cli}

`litedsp_gen` (or `python3 -m litedsp.gen`) takes one YAML file. It never runs a vendor tool,
except Vivado with `--vivado-ip` ([Standalone core](#tool-ipcore)).

| Option | Default | Effect |
|----------------------------|--------------------------|--------------------------------------|
| `config` | required | YAML file of the core |
| `--name` | from the YAML file | Name of the core module and of its Verilog file |
| `--output-dir` | `build` | Output directory |
| `--vivado-ip` | off | Package the core for Vivado IP Integrator |
| `--vivado-part` | `xc7a200tsbg484-3` | Part of the packaging and validation projects |
| `--vivado-validate` | off | Instantiate the package in a block design and synthesize it; needs `--vivado-ip` |

## Generator YAML keys {#opt-gen-yaml}

The keys below are read by `litedsp/gen.py`. A number may be given as a string, such as
`"0x1000"`; other keys are ignored.

| Key | Default | Meaning |
|------------------------------|------------------------|----------------------------------------|
| `flow` | none | Inline netlist ([Netlist keys](#opt-netlist)); exactly one of `flow` and `netlist` |
| `netlist` | none | Path of a netlist JSON, relative to the YAML file |
| `name` | netlist `name` + `_core` | Core name; `--name` takes precedence |
| `csr_base` | `0` | Address of the first register bank; a multiple of `2**axil_address_width` |
| `axil_address_width` | `16` | Width of the AXI-Lite byte address |
| `csr_data_width` | `32` | Register data width; only 32 is accepted |

## Netlist keys {#opt-netlist}

The keys below are read by `litedsp/flow/netlist.py`, from a JSON file or from the `flow` section
of a YAML file. [Netlist format](#tool-netlist) explains them.

| Key | Default | Meaning |
|-----------------------|------------|--------------------------------------------------------|
| `name` | `chain` | Name of the chain, default module name |
| `data_width` | `16` | Sample width given to the blocks that take one |
| `clock_ns` | `10.0` | Clock period, for the Vivado packaging and validation |
| `inputs`, `outputs` | empty | Top-level ports: `id`, and `layout` (default `iq`) |
| `blocks` | empty | Blocks: `id`, `type` (a registry key), `params` |
| `connections` | empty | Port references: `from`, `to` |
| `csr` | none | `base_address`, kept on load and save |
| `editor` | none | Node positions of the editor, ignored by code generation |

The `base_address` of the `csr` section is not used by the IP core: the base of the register
banks is the `csr_base` key of the YAML file.

## Flow generator command line {#opt-flow-cli}

`litedsp_flow` (or `python3 -m litedsp.flow.generate`) writes the Verilog of a chain, without the
AXI-Lite wrapper.

| Option | Default | Effect |
|---------------|-------------------|------------------------------------------------------------|
| `netlist` | required | Netlist JSON |
| `--out` | `build` | Output directory |
| `--name` | netlist `name` | Name of the top module |
| `--csr` | off | Build the blocks with their registers (`with_csr=True`) |

`python3 -m litedsp.flow.docgen` regenerates the block datasheets in `doc/blocks/`; `--out`
changes the directory and `--check` fails when they are stale. `litedsp_gui` takes no option.

## Host command line {#opt-cli}

`litedsp_cli` talks to a running SoC through `litex_server`. The global option comes before the
command.

| Command | Option | Default | Effect |
|--------------|----------------------|--------------|------------------------------------|
| all | `--csr-csv` | `csr.csv` | Register map of the build |
| `info` | | | List the LiteDSP blocks found |
| `nco` | `prefix` | required | Register prefix of the NCO, such as `ddc_nco` |
| `nco` | `--freq` | none | Frequency to set in Hz, signed |
| `capture` | `--capture` | none | Capture block prefix, when there are several |
| `capture` | `--reader` | none | CSR reader prefix, when there are several |
| `capture` | `--samples` | `1024` | Samples to read |
| `capture` | `--npy` | none | Save the samples to a `.npy` file |
| `spectrum` | `--capture`, `--reader`, `--samples` | as `capture` | Same as for `capture` |
| `spectrum` | `--sample-rate` | none | Sample rate in Hz, for the frequency axis |

## Bench options {#opt-bench}

The bench targets accept the options below; [Benches](#boards) describes them. The builds write
`csr.csv` in the current directory.

The target `bench/spectrum.py`:

| Option | Default | Effect |
|--------------------------|-----------------------|----------------------------------------|
| `--board` | `arty` | `arty` or `colorlight_5a_75b` |
| `--build` | off | Build the bitstream |
| `--load` | off | Load the bitstream, volatile |
| `--sys-clk-freq` | board default | System clock in Hz |
| `--capture-depth` | `2048` | Capture depth in samples |

The target `bench/stream.py`, for the Colorlight 5A-75B:

| Option | Default | Effect |
|--------------------------|-----------------------|----------------------------------------|
| `--build`, `--load` | off | Build, load the bitstream |
| `--revision` | `7.0` | Board revision |
| `--ip-address` | `192.168.1.50` | IP address of the SoC |
| `--host-ip` | `192.168.1.100` | Destination of the UDP packets |

The host scripts `bench/test_spectrum.py` and `bench/test_stream.py`:

| Option | Default | Effect |
|--------------------------|-----------------------|----------------------------------------|
| `--tone-freq` | `1e6` | Test tone frequency in Hz |
| `--tune-freq` | `1e6` | DDC tuning frequency in Hz; the scripts write its opposite, fix pending (PR #13) ([known issues](#intro-known-issues)) |
| `--csr-csv` | `csr.csv` | Register map of the build |
| `--samples` | `65536` | Samples to collect, `test_stream.py` only |

<!-- BEGIN generated by doc/manual/build_options.py: do not edit, regenerate. -->

## Block parameters {#opt-blocks}

The tables below list the constructor parameters of every block of the registry, one table per
family, as `name`=default. Each block is named by its registry key, the `type` of a netlist
block, followed by its display name.

The default shown is the one the flow uses for a netlist block. It is the registry value when the
registry sets one, in bold when it differs from the default of the Python constructor, and the
constructor default otherwise. A parameter shown without a value has no default and must be
given.

A long list default is summarized by its length. The possible values of a string parameter
follow it in parentheses. To keep the tables short, `data_width`=16 and `with_irq`=False are left
out where they are the default of the block: a block that lists no `data_width` takes 16-bit
samples.

`with_csr` is left out: it defaults to `True` in every block that takes it (some blocks have no
register even then, see [Register reference](#registers)). The chain builder passes its own value
([Chain builder](#tool-builder)): `True` for a standalone core, `False` for `litedsp_flow`
without `--csr`. The datasheet of each block, `doc/blocks/<key>.md` in
the repository ([catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md)),
describes each parameter; [Register reference](#registers) lists the registers.

### Signal generation {#opt-generation}

6 blocks of `litedsp/generation/`, described in [their chapter](#generation-mixing).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `chirp` Chirp (LFM) | `phase_bits`=32, `lut_depth`=1024 |
| `cordic_rot` CORDIC (rotate) | `angle_width`=None, `stages`=None, `mode`=rotation (rotation, vectoring) |
| `cordic_vec` CORDIC (vector) | `angle_width`=None, `stages`=None, **`mode`=vectoring** (rotation, vectoring) |
| `nco` NCO (DDS) | `phase_bits`=32, `lut_depth`=1024, `quarter_wave`=False |
| `noise_source` Noise (AWGN) | `n_sum`=16, `shift`=2, `seed`=19088743 |
| `pattern_source` Pattern source | `seed`=1 |

### Mixing {#opt-mixing}

5 blocks of `litedsp/mixing/`, described in [their chapter](#generation-mixing).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `channelizer` Channelizer | `n_channels`=4, **`decimation`=4**, `method`=fir (cic, fir), `phase_bits`=32, `fir_architecture`=classic (classic, pipelined) |
| `ddc` DDC | `decimation`=8, `method`=cic (cic, fir), `phase_bits`=32, `fir_architecture`=classic |
| `duc` DUC | `interpolation`=8, `method`=cic (cic, fir), `phase_bits`=32, `fir_architecture`=classic (classic, pipelined) |
| `mixer` Mixer (complex) | `shift`=None |
| `pfb_channelizer` PFB channelizer (scalable) | `n_channels`=4, `taps_per_channel`=8, `coefficients`=None, `architecture`=auto (auto, classic, folded, fft), `oversampling`=1 |

### Impairment correction {#opt-correction}

3 blocks of `litedsp/correction/`, described in [their chapter](#generation-mixing).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `dc_offset` DC offset | `mu`=10 |
| `derotator` Derotator (CFO) | `phase_bits`=32 |
| `iq_balance` I/Q balance | `coeff_frac`=14, `window_log2`=14 |

### Filtering {#opt-filter}

22 blocks of `litedsp/filter/`, described in [their chapter](#filters-rate).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `allpass` Allpass | `frac`=14 |
| `arb_resampler` Arbitrary resampler | `frac`=15, `ratio_int_bits`=8 |
| `bitstream_decimator` Bitstream (sigma-delta/PDM) decimator | `data_width`=24, `decimation`=64, `n_stages`=4, `diff_delay`=1, `r_max`=None, `staged`=False |
| `cic_decimator` CIC decimator | `decimation`=8, `n_stages`=3, `diff_delay`=1, `staged`=False |
| `cic_interpolator` CIC interpolator | `interpolation`=8, `n_stages`=3, `diff_delay`=1, `staged`=False |
| `comb_filter` Comb filter | `depth`=8 |
| `dc_blocker` DC blocker | `pole_shift`=5, `precision_bits`=0, `iq`=True |
| `dc_blocker_real` DC blocker (mono) | **`data_width`=24**, `pole_shift`=5, **`precision_bits`=8**, **`iq`=False** |
| `farrow` Farrow interpolator | `frac_bits`=15 |
| `fir_complex` FIR (complex) | `n_taps`=32, `symmetric`=False, `coefficients`=None, `shift`=None, `architecture`=classic (classic, pipelined, mac), `n_macs`=4 |
| `fir_real` FIR (real) | `n_taps`=32, `symmetric`=False, `shift`=None, `architecture`=classic (classic, pipelined, mac), `n_macs`=4 |
| `fir_decimator` FIR decimator | `n_taps`=32, `decimation`=8, `coefficients`=None, `shift`=None, `architecture`=classic, `prune_zeros`=False |
| `fir_interpolator` FIR interpolator | `n_taps`=32, `interpolation`=8, `coefficients`=None, `shift`=None, `architecture`=classic (classic, pipelined), `prune_zeros`=False |
| `halfband_dec` Halfband decimator | `n_taps`=23 |
| `halfband_int` Halfband interpolator | `n_taps`=23 |
| `hilbert` Hilbert | `n_taps`=23 |
| `iir_biquad` IIR biquad | `coefficients`=None, `frac_bits`=14, `architecture`=classic (classic, folded) |
| `equalizer` LMS equalizer | **`n_taps`=7**, `wfrac`=14, `wint`=4, `mu_shift`=20, `cma_egain`=0, `architecture`=classic (classic, pipelined), `update_pipeline`=False |
| `moving_average` Moving average | `length_log2`=4 |
| `notch` Notch | `frac`=14, `r`=0.96 |
| `pulse_shaper` Pulse shaper (RRC) | `sps`=4, `span`=8, `beta`=0.35 |
| `rational_resampler` Rational resampler | `interpolation`=3, `decimation`=2, `n_taps`=None |

### Rate conversion {#opt-rate}

5 blocks of `litedsp/rate/`, described in [their chapter](#filters-rate).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `decimator` Decimator | `decimation`=8, `method`=cic (cic, fir), `n_taps`=None, `cutoff`=0.4, `n_stages`=4, `fir_architecture`=classic |
| `downsampler` Downsampler | `factor_bits`=16 |
| `interpolator` Interpolator | `interpolation`=8, `method`=cic (cic, fir), `n_taps`=None, `cutoff`=0.4, `n_stages`=4, `fir_architecture`=classic (classic, pipelined) |
| `resampler_farm` Resampler farm | `n_channels`=4, `n_taps`=32, `decimation`=8, `coefficients`=None, `channel_coefficients`=None, `shift`=None, `architecture`=classic (classic, pipelined) |
| `upsampler` Upsampler | `factor_bits`=16, `zero_stuff`=False |

### Level control {#opt-level}

13 blocks of `litedsp/level/`, described in [their chapter](#level-analysis).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `agc` AGC | `gain_frac`=8, `mu`=8, `gain_max`=None, `beta_shift`=2, `delayed_feedback`=False, `feedback_delay`=None |
| `cfr` CFR (peak cancellation) | `pulse_span`=16, `threshold`=None, `cutoff`=0.25, `architecture`=classic (classic, pipelined) |
| `clipper` Clipper | none |
| `dpd` DPD actuator | `n_taps`=3, `lut_depth`=64, `coeff_frac`=14 |
| `envelope` Envelope detector | `attack`=2, `release`=6 |
| `exp2` Exp2 (antilog) | `in_width`=16, `frac_bits`=8, `out_frac`=20, `out_width`=25 |
| `gain` Gain | `gain_frac`=None |
| `log_power` Log power (dB) | `in_width`=32, `out_frac`=4 |
| `log2` Log2 | `in_width`=32, `frac_bits`=8, `lut`=False |
| `power` Power meter | `max_window_log2`=20 |
| `rms` RMS | `window_log2`=8, `max_window_log2`=20 |
| `saturate` Saturate | `in_width`=None, `shift`=0 |
| `squelch` Squelch | none |

### Analysis and measurement {#opt-analysis}

14 blocks of `litedsp/analysis/`, described in [their chapter](#level-analysis).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `bit_reverse` Bit-reverse reorder | `N`=64, `layout`=None, `fft_latency`=0 |
| `energy_detector` Energy detector | `avg_shift`=10, `threshold_log2`=3 |
| `error_counter` Error counter | none |
| `fft_iter` FFT (iterative) | **`N`=64**, `twiddle_width`=16, `registered_butterfly`=False |
| `parallel_fft` FFT (parallel, P samples/clk) | `N`=64, `n_samples`=2 (2, 4), `twiddle_width`=16, `core_architecture`=classic (classic, folded), `implementation`=split (split, native), `feedback_pipeline`=False, `complex_multiplier`=four |
| `fft` FFT (SDF) | **`N`=64**, `twiddle_width`=16, `inverse`=False, `scaling`=scaled (scaled, bfp), `architecture`=classic (classic, folded) |
| `goertzel` Goertzel | **`N`=64**, **`k`=8**, `coeff_frac`=14, `architecture`=classic (classic, folded) |
| `histogram` Histogram | `bits`=8, `window_log2`=12 |
| `magnitude` Magnitude (approx) | `beta_shift`=2, `method`=approx (approx, cordic) |
| `magnitude_cordic` Magnitude (CORDIC) | `beta_shift`=2, **`method`=cordic** (approx, cordic) |
| `psd` PSD | `N`=64, `fft_latency`=None, `avg_log2`=4 |
| `stats` Stats | `window_log2`=8 |
| `welch` Welch PSD | **`N`=64**, `avg_log2`=2, `window`=hann (hann, hamming, blackman, rect), `overlap`=0 |
| `window` Window | **`n`=64**, `window`=hann (hann, hamming, blackman, rect) |

### Communications {#opt-comm}

51 blocks of `litedsp/comm/`, described in [their chapter](#comm).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `am_demod` AM demod | `pole_shift`=8 |
| `am_modulator` AM modulator | `carrier`=baseband (baseband, nco), `phase_bits`=32, `lut_depth`=1024 |
| `bch_decoder` BCH decoder | `m`=4 (4, 5, 6, 7, 8), `t`=2 (1, 2, 3, 4), `field_poly`=None |
| `bch_encoder` BCH encoder | `m`=4 (4, 5, 6, 7, 8), `t`=2 (1, 2, 3, 4), `field_poly`=None |
| `block_deinterleaver` Block deinterleaver | `rows`=5, `cols`=255, `width`=8 |
| `block_interleaver` Block interleaver | `rows`=5, `cols`=255, `width`=8 |
| `carrier_loop` Carrier loop (PLL) | `phase_bits`=32, `lut_depth`=1024, `kp_shift`=6, `ki_shift`=14, `decision_directed`=False, **`detector`=pll** (pll, bpsk, qpsk), `architecture`=classic (classic, pipelined) |
| `ccsds_rs_decoder` CCSDS RS decoder | `architecture`=pipelined (classic, pipelined) |
| `ccsds_rs_encoder` CCSDS RS encoder | none |
| `cfo_estimator` CFO estimator (coarse) | `delay`=16, `span_log2`=8, `angle_width`=16, `phase_bits`=32 |
| `convolutional_deinterleaver` Convolutional deinterleaver | `branches`=12, `depth`=17, `width`=8 |
| `conv_encoder` Convolutional encoder | `constraint`=7, `polys`=[121, 91] |
| `convolutional_interleaver` Convolutional interleaver | `branches`=12, `depth`=17, `width`=8 |
| `correlator` Correlator | **`sequence`=list of 7** |
| `crc` CRC | `width`=16, `poly`=4129, `init`=65535 |
| `depuncturer` Depuncturer (LLR) | **`pattern`=list of 2**, `n`=2, `llr_bits`=4 |
| `descrambler` Descrambler (LFSR) | `polynomial`=[18, 23] |
| `diff_decoder` Differential decoder | `modulus`=4 |
| `diff_encoder` Differential encoder | `modulus`=4 |
| `fm_demod` FM demod | `angle_width`=16 |
| `fm_modulator` FM modulator | `phase_bits`=32, `lut_depth`=1024 |
| `frame_sync` Frame sync (preamble) | **`sequence`=list of 7**, `threshold_frac`=14, `frame_len`=None, `peak_window`=4, `architecture`=classic (classic, pipelined) |
| `fsk_modulator` FSK / GFSK modulator | `bits_per_symbol`=1 (1, 2), `sps`=4, **`bt`=0.5**, `span`=4, `phase_bits`=32, `lut_depth`=1024, `fir_architecture`=classic (classic, mac), `n_macs`=4 |
| `gray_demapper` Gray demapper | `width`=2, `n_lanes`=1 |
| `gray_mapper` Gray mapper | `width`=2, `n_lanes`=1 |
| `hamming_decoder` Hamming decoder | `m`=3 (3, 4, 5, 6), `secded`=False (False, True) |
| `hamming_encoder` Hamming encoder | `m`=3 (3, 4, 5, 6), `secded`=False (False, True) |
| `hdlc_deframer` HDLC deframer | none |
| `hdlc_framer` HDLC framer | `preamble`=1 |
| `ldpc_decoder` LDPC decoder (802.11n) | `llr_bits`=4, `max_iters`=8 |
| `ldpc_decoder_z_parallel` LDPC decoder (z-parallel) | `llr_bits`=4, `max_iters`=8, `parallelism`=27 |
| `ldpc_encoder` LDPC encoder (802.11n) | none |
| `line_decoder` Line decoder (NRZI) | `code`=nrzi_s (nrzi_s, nrzi_m, manchester, diff_manchester), `invert`=False |
| `line_encoder` Line encoder (NRZI) | `code`=nrzi_s (nrzi_s, nrzi_m, manchester, diff_manchester), `invert`=False |
| `manchester_decoder` Manchester decoder | **`code`=manchester**, `invert`=False |
| `manchester_encoder` Manchester encoder | **`code`=manchester**, `invert`=False |
| `cp_insert` OFDM CP insert | `fft_size`=64, `cp_len`=16 |
| `cp_remove` OFDM CP remove | `fft_size`=64, `cp_len`=16 |
| `ofdm_equalizer` OFDM equalizer (1-tap) | `fft_size`=64, `coeff_frac`=14 |
| `phase_detect` Phase detector | `angle_width`=16 |
| `pm_modulator` Phase modulator | `phase_bits`=32, `lut_depth`=1024 |
| `puncturer` Puncturer | **`pattern`=list of 2**, `n`=2 |
| `rs_decoder` RS decoder (255,k) | `n`=255, `k`=223, `architecture`=classic (classic, pipelined), `field_poly`=285, `fcr`=0, `prim`=1 |
| `rs_encoder` RS encoder (255,k) | `n`=255, `k`=223, `field_poly`=285, `fcr`=0, `prim`=1 |
| `scrambler` Scrambler (LFSR) | `polynomial`=[18, 23] |
| `slicer` Slicer | `bits_per_axis`=1, `spacing`=8192 |
| `soft_demapper` Soft demapper (LLR) | `bits_per_axis`=1, `spacing`=8000, `llr_bits`=4 |
| `ssb_modulator` SSB modulator | `n_taps`=31 |
| `symbol_mapper` Symbol mapper | `bits_per_axis`=1, `spacing`=8192 |
| `timing_recovery` Timing recovery (M&M) | `sps`=2, `frac`=16, `gain_mu`=0.1, `gain_omega`=None, `ted`=mm, `architecture`=classic |
| `viterbi_decoder` Viterbi decoder | `constraint`=7, `polys`=[121, 91], `traceback`=None, `llr_bits`=None, `metric_width`=None, `decision_memory`=False, `normalize_interval`=16, `acs_parallelism`=None |

### Stream utilities and links {#opt-stream}

23 blocks of `litedsp/stream/`, described in [their chapter](#stream-frontend).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `capture` Capture (scope) | **`depth`=256**, `with_wishbone`=False |
| `channel_demux` Channel demux | `n`=2, `layout`=None |
| `channel_mux` Channel mux | `n`=2, `layout`=None |
| `cdc` Clock-domain crossing | `cd_from`=sys, `cd_to`=sys, `depth`=8 |
| `combine` Combine (sum) | `n_channels`=2, `layout`=None |
| `conjugate` Conjugate | none |
| `csr_sink` CSR sink | none |
| `csr_source` CSR source | none |
| `deframer` Deframer | none |
| `delay` Delay | `depth`=1, `layout`=None |
| `framer` Framer | `length`=256, `max_length`=65536 |
| `iq_pack` I/Q pack | `ratio`=4 |
| `iq_unpack` I/Q unpack | `ratio`=4 |
| `negate` Negate | none |
| `null_sink` Null sink | none |
| `skid_buffer` Skid buffer | none |
| `split` Split (fan-out) | `n`=2, `layout`=None |
| `stream_fifo` Stream FIFO | `depth`=16, `layout`=None |
| `swap_iq` Swap I/Q | none |
| `tdm_demux` TDM demux | `n_channels`=2, `data_width`=24 |
| `tdm_mux` TDM mux (interleave) | `n_channels`=2, `data_width`=24 |
| `time_untagger` Time untagger | `width`=64 |
| `timestamper` Timestamper | `width`=64, `stream_id`=0 |

### Motor control {#opt-motor}

19 blocks of `litedsp/motor/`, described in [their chapter](#motor).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `pwm` 3-phase PWM | `period_width`=16, `dead_time_width`=8 |
| `angle_ramp` Angle ramp | `angle_width`=16, `phase_bits`=32 |
| `angle_tracker` Angle tracker (PLL) | `angle_width`=16, `frac_bits`=14, `kp_shift`=4, `ki_shift`=10 |
| `clarke` Clarke (abc to ab) | `three_wire`=False |
| `dq_controller` d/q current controller | `gain_width`=16, `gain_frac`=12, `anti_windup`=conditional (conditional, clamp, none), `decoupling`=False |
| `foc` FOC current controller | `angle_width`=16, `lut_depth`=1024, `three_wire`=False, `gain_width`=16, `gain_frac`=12, `anti_windup`=conditional (conditional, clamp, none), `decoupling`=False |
| `hall_decoder` Hall sensor decoder | `angle_width`=16, `timer_width`=24, `interpolate`=True, `filter_length`=2 |
| `inverse_clarke` Inverse Clarke | none |
| `inverse_park` Inverse Park | `angle_width`=16, `lut_depth`=1024, `method`=rom (rom, cordic), `stages`=None |
| `overcurrent_trip` Over-current trip | none |
| `park` Park (ab to dq) | `angle_width`=16, `lut_depth`=1024, `method`=rom (rom, cordic), `stages`=None |
| `pi_controller` PI controller | `gain_width`=16, `gain_frac`=12, `anti_windup`=conditional (conditional, clamp, none), `setpoint_stream`=False |
| `quadrature_decoder` Quadrature encoder | `angle_width`=16, `position_width`=16, `speed_width`=16, `filter_length`=2, `scale_frac`=16 |
| `resolver` Resolver-to-digital | `angle_width`=16, `decimation`=32, `kp_shift`=3, `ki_shift`=8, `frac_bits`=14, `stages`=None |
| `sigma_delta_filter` Sigma-delta current sense | `n_channels`=3, `decimation`=64, `n_stages`=3, `r_max`=256, `fast_decimation`=16 |
| `sincos` Sin/Cos (angle) | `angle_width`=16, `lut_depth`=1024, `method`=rom (rom, cordic), `stages`=None |
| `slew_limiter` Slew limiter | none |
| `smo_observer` Sliding-mode observer | `angle_width`=16, `gain_width`=16, `gain_frac`=12, `stages`=None |
| `svpwm` SVPWM modulator | `injection`=minmax (minmax, none) |

### Audio {#opt-audio}

19 blocks of `litedsp/audio/`, described in [their chapter](#audio).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `chorus` Chorus / flanger | `data_width`=24, `n_channels`=2, **`max_delay`=512**, `coeff_frac`=15, **`modulation`=True**, `mod_frac`=8 |
| `compressor` Compressor | `data_width`=24, `n_channels`=2, `lookahead`=0, `preset`=compressor (compressor, limiter, gate) |
| `delay_line` Delay line (echo) | `data_width`=24, `n_channels`=2, `max_delay`=4096, `coeff_frac`=15, `modulation`=False, `mod_frac`=8 |
| `dither` Dither / requantizer | `data_width`=24, `out_width`=16, `n_channels`=2, `shaping`=none (none, ef1, ef2), `seed`=625341585 |
| `i2s_rx` I2S receiver | `data_width`=24, `sample_width`=24, `slot_width`=32, `n_channels`=2, `fmt`=i2s (i2s, left_justified, right_justified, tdm), `mode`=slave (slave, master), `bclk_div`=8 |
| `i2s_tx` I2S transmitter | `data_width`=24, `sample_width`=24, `slot_width`=32, `n_channels`=2, `fmt`=i2s (i2s, left_justified, right_justified, tdm), `mode`=master (master, slave), `bclk_div`=8 |
| `lfo` LFO | `phase_bits`=32, `lut_depth`=256 |
| `limiter` Limiter (lookahead) | `data_width`=24, `n_channels`=2, **`lookahead`=32**, **`preset`=limiter** (compressor, limiter, gate) |
| `loudness` Loudness (BS.1770) | `data_width`=24, `n_channels`=2, `sample_rate`=48000, `hop_samples`=4800, `channel_weights`=None, `coeff_width`=32, `frac_bits`=28 |
| `noise_gate` Noise gate / expander | `data_width`=24, `n_channels`=2, `lookahead`=0, **`preset`=gate** (compressor, limiter, gate) |
| `audio_eq` Parametric EQ | `data_width`=24, `n_bands`=3, `n_channels`=2, `coeff_width`=32, `frac_bits`=28, `sections`=None, `error_feedback`=1 |
| `sigma_delta_dac` PDM DAC | `data_width`=24, `n_channels`=1, `interpolation`=64, `order`=2, `clk_div`=16 |
| `pdm_rx` PDM receiver | `data_width`=24, `n_channels`=2, `decimation`=64, `n_stages`=4, `clk_div`=16, `dual_edge`=True, `with_dc_blocker`=True, `dc_pole_shift`=10, `with_compensation`=False, `n_comp_taps`=15 |
| `peak_meter` Peak meter | `data_width`=24, `n_channels`=2, `decay_shift`=12, `clip_threshold`=None |
| `reverb` Reverb | `data_width`=24, `n_channels`=2, `comb_delays`=list of 4, `allpass_delays`=[556, 441], `stereo_spread`=23, `coeff_frac`=15 |
| `sigma_delta_mod` Sigma-delta modulator | `data_width`=24, `interpolation`=64, `order`=2 (1, 2) |
| `stereo_matrix` Stereo matrix (M/S, pan) | `data_width`=24, `coeff_width`=18, `coeff_frac`=15 |
| `volume` Volume (ramped) | `data_width`=24, `n_channels`=2, `gain_frac`=None, `ramp_shift`=8 |
| `wet_dry_mix` Wet/dry mix | `data_width`=24, `n_channels`=2, `coeff_frac`=15 |

### Radar and sonar {#opt-radar}

17 blocks of `litedsp/radar/`, described in [their chapter](#radar).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `cfar_2d` 2-D CA-CFAR detector | `n_range_bins`=64, `n_doppler_bins`=16, `n_train`=[4, 2], `n_guard`=[1, 1], `data_width`=17, `alpha_width`=16, `threshold_frac`=8 |
| `alpha_beta_tracker` Alpha-beta tracker | `n_tracks`=4, `index_width`=12, `frac_bits`=4, `velocity_frac`=8, `gain_frac`=8, `data_width`=17 |
| `beamformer` Beamformer | `n_elements`=4, `n_beams`=1, `weight_width`=16, `weight_frac`=14, `shift`=None |
| `ca_cfar` CA-CFAR detector | `n_train`=8, `n_guard`=2, `data_width`=17, `alpha_width`=16, `threshold_frac`=8 |
| `clutter_map` Clutter map | `n_range_bins`=64, `n_doppler_bins`=1, `data_width`=17, `avg_shift`=3, `alpha_width`=16, `threshold_frac`=8 |
| `corner_turn` Corner turn (fast to slow time) | `n_range_bins`=64, `n_pulses`=16 |
| `doppler` Doppler processor | `n_pulses`=16, `window`=hann (rect, hann, hamming, blackman), `magnitude`=approx (approx, power), `twiddle_width`=16, `beta_shift`=2 |
| `kalman_tracker` Kalman tracker | `n_tracks`=4, `index_width`=12, `frac_bits`=4, `velocity_frac`=8, `cov_frac`=8, `cov_width`=24, `data_width`=17 |
| `monopulse` Monopulse angle | `angle_width`=16, `stages`=None |
| `mti` MTI canceller | `n_range_bins`=64, `order`=3, `shift`=None |
| `os_cfar` OS-CFAR detector | `n_train`=4, `n_guard`=2, `rank`=None, `data_width`=17, `alpha_width`=16, `threshold_frac`=8 |
| `peak_extractor` Peak extractor | `n_range_bins`=64, `n_doppler_bins`=16, `data_width`=17, `index_width`=12, `frac_bits`=4 |
| `pulse_compressor` Pulse compressor (chirp matched filter) | `pulse_len`=16, `bandwidth`=0.5, `window`=rect (rect, hann, hamming, blackman), `shift`=None, `phase_bits`=32, `lut_depth`=1024, `fir_architecture`=classic (classic, pipelined, mac), `n_macs`=4 |
| `pulse_generator` Pulse generator | `pulse_len`=32, `bandwidth`=0.5, `pri`=128, `n_pulses`=16, `pri_width`=24, `phase_bits`=32, `lut_depth`=1024 |
| `range_gate` Range gate (PRI timer) | `n_range_bins`=64, `n_pulses`=16, `pri`=128, `gate_start`=0, `pulse_width`=16, `pri_width`=24 |
| `target_list` Target list | `max_targets`=16, `data_width`=17, `index_width`=12, `frac_bits`=4 |
| `tvg` Time-varying gain | `n_range_bins`=1024, `gain_frac`=8, `max_gain_log2`=8 |

### Image and video {#opt-image}

32 blocks of `litedsp/image/`, described in [their chapter](#image).

| Block | Parameters |
|--------------------------------------------|----------------------------------------------------|
| `kernel_2d` 2-D kernel (3x3) | `data_width`=8, `n_channels`=1 (1, 3), `kernel_size`=3, **`coefficients`=list of 9**, `coeff_width`=10, `shift`=0, `offset`=0, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `kernel_5x5` 2-D kernel (5x5) | `data_width`=8, `n_channels`=1 (1, 3), **`kernel_size`=5**, **`coefficients`=list of 25**, `coeff_width`=10, **`shift`=8**, `offset`=0, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `alpha_blend` Alpha blend | `data_width`=8, `n_channels`=3 (1, 3), `alpha`=128, `with_alpha_sink`=False |
| `downscaler` Box downscaler | `data_width`=8, `n_channels`=1 (1, 3), `decimation`=2 (2, 4, 8), **`width`=64**, **`height`=48**, `max_width`=None, `coord_bits`=12 |
| `box_overlay` Box overlay | `data_width`=8, `n_channels`=3 (1, 3), `n_boxes`=4, `thickness`=1, `boxes`=None, `coord_bits`=12 |
| `color_matrix` Colour matrix | `data_width`=8, `n_out`=3, **`coefficients`=list of 9**, `in_offsets`=[0, 0, 0], `out_offsets`=[0, 0, 0], `coeff_width`=16, `coeff_frac`=12 |
| `crop` Crop (ROI) | `data_width`=8, `n_channels`=3 (1, 3), `x0`=0, `y0`=0, **`roi_width`=32**, **`roi_height`=24**, `coord_bits`=12 |
| `debayer` Debayer (bilinear) | `data_width`=8, `pattern`=rggb (rggb, bggr, grbg, gbrg), **`width`=64**, `max_width`=None, `border`=mirror (mirror, replicate, zero) |
| `dilate` Dilation (3x3 max) | `data_width`=8, `n_channels`=1 (1, 3), **`rank`=8**, **`width`=64**, `max_width`=None, `border`=replicate |
| `erode` Erosion (3x3 min) | `data_width`=8, `n_channels`=1 (1, 3), **`rank`=0**, **`width`=64**, `max_width`=None, `border`=replicate |
| `pixel_histogram` Frame histogram | `data_width`=8, `n_channels`=1 (1, 3), `channel`=0, `bins_log2`=8 (4, 5, 6, 7, 8), `max_pixels`=2073600 |
| `pixel_stats` Frame statistics tap | `data_width`=8, `n_channels`=1 (1, 3), `channel`=0, `zones`=4 (1, 2, 4, 8), `max_pixels`=2073600, `coord_bits`=12 |
| `gamma` Gamma (LUT) | `data_width`=8, **`n_channels`=3**, `shared`=True, **`gamma`=2.2** |
| `gaussian_blur` Gaussian blur | `data_width`=8, `n_channels`=1 (1, 3), `kernel_size`=3, **`coefficients`=list of 9**, `coeff_width`=10, **`shift`=4**, `offset`=0, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `laplacian` Laplacian | `data_width`=8, `n_channels`=1 (1, 3), `kernel_size`=3, **`coefficients`=list of 9**, `coeff_width`=10, `shift`=0, **`offset`=128**, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `line_buffer` Line buffer (window) | `data_width`=8, `n_channels`=1 (1, 3), `kernel_size`=3 (3, 5, 7), **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `mask_blend` Mask blend | `data_width`=8, `n_channels`=3 (1, 3), `alpha`=128, **`with_alpha_sink`=True** |
| `pixel_fifo` Pixel FIFO | **`depth`=256**, `data_width`=8, `n_channels`=3 (1, 3) |
| `pixel_gain` Pixel gain / offset | `data_width`=8, `n_channels`=3 (1, 3), `gain_frac`=8 |
| `pixel_lut` Pixel LUT | `data_width`=8, `n_channels`=1 (1, 3), `shared`=True (True, False), `gamma`=1.0 |
| `pixel_pack` Pixel pack | `data_width`=8, `format`=rgb888 (rgb888, xrgb8888, rgb565, mono) |
| `pixel_pattern` Pixel pattern source | `data_width`=8, `n_channels`=3 (1, 3), **`width`=64**, **`height`=48**, `mode`=bars (const, ramp, bars, checker, counter, bayer), `coord_bits`=12 |
| `pixel_unpack` Pixel unpack | `data_width`=8, `format`=rgb888 (rgb888, xrgb8888, rgb565, mono), **`width`=64**, `coord_bits`=12 |
| `pixel_from_video` Pixels from LiteX video | `data_width`=8, **`width`=64**, **`height`=48**, `coord_bits`=12 |
| `pixel_to_video` Pixels to LiteX video | `data_width`=8, `coord_bits`=12 |
| `rank_filter` Rank filter (median) | `data_width`=8, `n_channels`=1 (1, 3), `rank`=4, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `rgb_to_gray` RGB to grey (601) | `data_width`=8, **`n_out`=1**, **`coefficients`=list of 3**, `in_offsets`=[0, 0, 0], **`out_offsets`=[0]**, `coeff_width`=16, `coeff_frac`=12 |
| `rgb_to_ycbcr` RGB to YCbCr (601) | `data_width`=8, `n_out`=3, **`coefficients`=list of 9**, `in_offsets`=[0, 0, 0], **`out_offsets`=[16, 128, 128]**, `coeff_width`=16, `coeff_frac`=12 |
| `sharpen` Sharpen | `data_width`=8, `n_channels`=1 (1, 3), `kernel_size`=3, **`coefficients`=list of 9**, `coeff_width`=10, `shift`=0, `offset`=0, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero) |
| `sobel` Sobel edge magnitude | `data_width`=8, **`width`=64**, `max_width`=None, `border`=replicate (replicate, mirror, zero), `mode`=l1 (l1, linf, approx), `shift`=3, `with_direction`=False |
| `threshold` Threshold (hysteresis) | `data_width`=8, `high`=128, `low`=None, `invert`=False |
| `ycbcr_to_rgb` YCbCr to RGB (601) | `data_width`=8, `n_out`=3, **`coefficients`=list of 9**, **`in_offsets`=[16, 128, 128]**, `out_offsets`=[0, 0, 0], `coeff_width`=16, `coeff_frac`=12 |

<!-- END generated by doc/manual/build_options.py -->
