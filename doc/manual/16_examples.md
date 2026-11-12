# Examples and application notes {#examples}

This chapter lists the examples of the repository and folds in the application notes of the RF
families. Each example assembles real blocks into a chain, runs it in the Migen simulation on a
NumPy stimulus, prints its results and asserts a golden property. All the results and plots of
this chapter come from simulation, not from a board.

## Running an example {#ex-run}

Every example is a script of `examples/`, run from the root of the repository. The examples use
the stream simulator of the tests (`run_stream()` of `test/common.py`) and exit with an error
when their golden property fails. The examples of the application notes also write plots, with
Matplotlib in headless mode, and accept `--plot-dir` to choose where.

```sh
python3 examples/fm_receiver.py
python3 examples/fm_stereo_receiver.py --plot-dir build/an001
```

CI runs every application-note example, as is, and generates every YAML configuration
(`test/test_examples.py`). The Migen simulation is slow: a long example takes minutes. AN001,
AN002 and AN005 read an environment variable (`AN001_SAMPLES`, `AN002_RTL_SYMBOLS`,
`AN005_RTL_DEPTH`) to change the run during development.

## Example chains {#ex-chains}

The examples below show one technique each. They are small and fast, and good starting points
for a chain of your own.

| Example | Chain | Shows |
|----------------------------------|----------------------------------|--------------------------|
| `ddc_chain.py` | NCO, mixer, FIR, downsampler | Down-conversion, [first chain](#gs-chain) |
| `duc_chain.py` | Interpolator, NCO, mixer | Up-conversion |
| `fm_receiver.py` | FM discriminator, FIR decimator | FM demodulation, audio decimation |
| `qpsk_rx.py` | RRC filter, timing recovery, slicer | Symbol timing, QPSK decisions |
| `spectrum_analyzer.py` | Window, FFT, PSD | Averaged power spectrum |
| `wideband_rx.py` | DDC, FIFO, framer, I/Q packing | Capture front end, framing |
| `loopback_ber.py` | PRBS source, split, delay and FIFO, error counter | Self-checking integrity harness |
| `integrated_ip.py` | DC blocker, gain, framer | AXI-Stream ports, register map, Verilog |

`wideband_rx.py` prepares samples for a bus: a FIFO absorbs rate jitter, the framer marks
packets with `last`, and the packer puts several narrow I/Q samples in one wide bus word.
`loopback_ber.py` compares a PRBS stream on two branches, a delay and a FIFO of different
latencies, through the error counter, with zero errors: the harness of
[Debugging](#dbg-counter). `integrated_ip.py` previews the standalone core of
[Standalone core](#tool-ipcore).

## Application notes {#ex-notes}

The application notes pair a larger example with a documented objective, a block diagram and
measured results. The notes of the RF families, listed below, are sections of this chapter.
Those of the application families are in their chapters: [AN004](#rad-an004),
[AN009](#mot-an009), [AN010](#aud-an010), [AN011](#rad-an011) and [AN012](#img-an012)
([Using the application families](#apps-using) lists them).

| Note | Example | Subject |
|-------|--------------------------------------|----------------------------------------|
| AN001 | `fm_stereo_receiver.py` | FM stereo broadcast receiver |
| AN002 | `qpsk_modem.py` | DQPSK modem loopback and BER curve |
| AN003 | `spectrum_monitor.py` | Spectrum monitor with waterfall |
| AN005 | `ccsds_telemetry.py` | Concatenated FEC telemetry |
| AN006 | `adsb_receiver.py` | ADS-B and Mode S receiver |
| AN007 | `ais_receiver.py` | AIS GMSK receiver |
| AN008 | `css_receiver.py` | Chirp spread-spectrum receiver |
| AN013 | `fsk_hamming_link.py` | GFSK link with Hamming code and HDLC |

The original notes are in `doc/app_notes/` of the repository; their resource tables are older
than the recorded results of [Performance](#performance), which are the reference.

## Standalone core configurations {#ex-configs}

The YAML files of `examples/` describe complete chains for the standalone core generator; each
one builds with `litedsp_gen examples/<file>`, with no vendor tool. [Generator
configuration](#tool-gen) explains the format. The configurations of the application
families, `foc_core.yml`, `audio_core.yml` and `image_core.yml`, are in [Using the application
families](#apps-using).

| Configuration | Chain | Family |
|---------------------------------------|----------------------------------------|-------------------|
| `ddc_core.yml` | NCO, delay, mixer, FIR, downsampler | Mixing |
| `qpsk_receiver_core.yml` | QPSK Costas loop, M&M timing recovery, hard decisions | Communications |
| `spectrum_core.yml` | Hann window, FFT, PSD | Analysis |

## AN001: FM stereo broadcast receiver {#ex-an001}

This note decodes the full multiplex of an FM stereo broadcast with a LiteDSP chain, from the
mono receiver of `fm_receiver.py` to separate left and right channels.

The golden property is the stereo separation: with a program on the left channel only, the right
output must stay at least 30 dB below the left one, with an audio SNR of at least 25 dB on the
left tone.

### The multiplex {#ex-an001-mpx}

An FM stereo station transmits a composite baseband, the multiplex (MPX). It carries the sum of
the channels L+R as mono audio, a 19 kHz pilot tone, and the difference L-R on a suppressed
38 kHz subcarrier, twice the pilot frequency. A mono receiver keeps the sum; a stereo receiver
rebuilds the 38 kHz carrier, demodulates the difference and recombines the two.

The example generates the multiplex in NumPy, as `0.4 (L+R) + 0.2 pilot + 0.4 (L-R) cos(38 kHz)`,
frequency-modulates it at baseband, and drives it through the chain at 152 kHz, eight times the
pilot frequency. The figure below shows the spectrum after the FM discriminator of the chain.

![AN001 multiplex spectrum after the FM discriminator: the mono audio, the 19 kHz pilot and the
L-R sidebands around 38 kHz. Simulation.](ex_an001_mpx_spectrum.png){width=90%}

### The chain {#ex-an001-chain}

The figure below shows the chain. The discriminator output feeds three paths: the mono low-pass
decimator, the L-R mixer, and the regeneration of the 38 kHz carrier from the pilot. The two
decimated paths meet in one complex adder that produces both channels.

![AN001 chain. The 38 kHz carrier is regenerated from the pilot (19 kHz band-pass, square,
38 kHz band-pass) and demodulates the L-R band; a FIFO on the direct path absorbs the fill of
the pilot path; the adder matrix forms L on I and R on Q.](ex_an001.svg)

The carrier comes from squaring the pilot, the trick of analog stereo decoders, with no PLL: a
19 kHz band-pass filter isolates the pilot, a mixer multiplies it by itself, and the square holds
a 38 kHz term that a second band-pass filter keeps. This carrier is phase coherent with the
transmitted subcarrier by construction.

The phase stays aligned by design. All filters are linear-phase FIRs, and a 38 kHz period is 4
samples at 152 kHz. The two band-pass filters have 33 and 25 taps, delays of 16 and 12 samples:
their sum, 28, is a whole number of carrier periods, so the regenerated carrier arrives in phase.

The gains are matched by design. The gain of the L-R path depends on the amplitude of the
regenerated carrier; the example predicts it with the bit-exact NumPy models of `test/models.py`
and puts the compensation into the taps of the L-R low-pass decimator, so the matrix cancels
exactly.

The matrix is one `LiteDSPIQAdd`. The mono signal drives both I and Q of its first input, and
plus and minus L-R drive its second, so one saturating complex add gives L on I and R on Q. A
FIFO on the direct path absorbs the pipeline fill of the pilot path, since the two paths join
at the L-R mixer.

The squaring mixer takes the pilot directly on both its inputs, not through a split: the same
stream drives both sinks, which the mixer consumes together.

### Simplifications {#ex-an001-limits}

The example is a demonstration subset, not a broadcast receiver:

- the pilot is at 20 % of the multiplex instead of the 9 % of the broadcast standard, for
  headroom in the Q1.15 squaring path, whose output scales with the square of the pilot level;
- the filters are narrow and short, 25 to 33 taps with a 7.6 kHz audio cutoff, sized for a tone
  program and simulation speed; real program material needs sharper filters;
- there is no de-emphasis, no mono and stereo blend on pilot detection, and no RDS decoding.

### Results {#ex-an001-results}

The run below is the default one: 1536 multiplex samples through the Migen simulation, a
1187.5 Hz tone on the left channel only.

```console
$ python3 examples/fm_stereo_receiver.py --plot-dir build/an001
FM stereo receiver (AN001): fs=152 kHz, 1536 MPX samples, pilot-squaring 38 kHz regeneration
  L audio: 4391 counts rms, tone SNR 61.0 dB (vs LS-fitted 1187.5 Hz tone)
  R audio: 4.0 counts rms (crosstalk)
  stereo separation: 60.8 dB
  PASS: L-only program decoded with >= 30 dB separation, >= 25 dB audio SNR
  plots -> build/an001/an001_mpx_spectrum.png, build/an001/an001_audio.png
```

The left output carries the tone and the right output a residue 60.8 dB lower, well past the
30 dB gate. The gates are set with a wide margin so that seed changes and parameter tweaks do
not make CI fail. The figure below shows the decoded channels.

![AN001 decoded audio: the left channel carries the tone, the right channel is a residue.
Simulation.](ex_an001_audio.png){width=90%}

The blocks of the note are the FM discriminator, the real FIR filter in its symmetric form, the
mixer, the FIR decimator, the stream FIFO and split, and the complex adder; their datasheets are
in the [block catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md).

## AN003: spectrum monitor with waterfall {#ex-an003}

This note builds a timestamped spectrum monitor from the analysis blocks. On one stimulus, two
continuous tones, a short chirp burst and noise, it shows the two complementary views of a power
spectrum: Welch averaging with overlap, stacked into a waterfall, and max-hold, which keeps the
peak of each bin and catches the transient burst that averaging smears.

### The chain {#ex-an003-chain}

The figure below shows the chain. The stream is tagged with its sample time at the input, the
tags are stripped before the Welch block, and the spectra go to the host, which stacks them.

![AN003 chain. The time core counts samples; the timestamper tags each input sample; the Welch
block windows, transforms and accumulates overlapping segments into spectra.](ex_an003.svg)

`LiteDSPWelchPSD` composes the window, the FFT and the PSD accumulator, and adds an N-sample
history memory to replay the overlap. The example uses N = 64 bins, a Hann window, 50 % overlap
and two segments per spectrum.

With 50 % overlap, each 64-sample segment is followed by 32 replay cycles, so the sustained
input rate is bounded by about half the clock rate.

The PSD accumulator has several modes: linear average, exponential average, max-hold and
min-hold. A register write switches the mode on hardware, and a clear restarts the max-hold
trace. The example runs the simulation twice on the same stimulus, once in linear mode for the
waterfall and once in max-hold mode.

### Timestamps on the waterfall axis {#ex-an003-time}

The y-axis of the waterfall is absolute time, in clock cycles of the time core, even though the
overlap replay and the readout stall the input. The time core counts every clock from an epoch,
1,000,000 here (a register write sets it on hardware); the timestamper tags every accepted input
sample with that count; the untagger removes the tags
before the time-agnostic Welch chain. [Timestamps](#stream-frontend) describes these blocks.

The PSD block has no fixed latency, so the example does not re-timestamp its output: it uses the
segment arithmetic instead.

With two segments per spectrum and 50 % overlap, waterfall row `m` averages the input samples
from `64m` to `64m + 95`; the row is labelled with the recorded tag of sample `64m`. Stall
cycles appear as gaps between the tags of consecutive samples, so the rows are not evenly spaced
in time.

From the waterfall alone, the script finds the onset of the chirp burst: the first row whose
chirp band exceeds the floor by 10 dB. It reports the time of that row and compares it with the
recorded tag of the first burst sample.

### Results {#ex-an003-results}

The stimulus has 1500 samples: tones at bins 9 and 23 with amplitude 6000, a chirp of amplitude
5000 sweeping bins 36 to 56 during samples 560 to 880, and noise with a standard deviation of 60.

```console
$ python3 examples/spectrum_monitor.py --plot-dir build/an003
Spectrum monitor: N=64, 2 avg/spectrum, 50% overlap, epoch=1,000,000
  chain latencies: timestamper=0 + untag=0 + window=2 + fft=63 = 65 samples [...]
  ingress: first sample @ 1,000,001, 2496 stall cycles absorbed over 1344 samples [...]
  noise floor ~  -47.0 dB
    detected peak bin  9 (injected  9):   -0.0 dB
    detected peak bin 23 (injected 23):   -0.0 dB
  chirp band bins 38..54: max-hold - average = 13.4 dB (median), [...]
  chirp onset: row 8 @ 1,001,441 (true ingress 1,001,521, [...])
  PASS: tones within a bin, max-hold captures the chirp the average smears, [...]
  plots -> build/an003/an003_waterfall.png, build/an003/an003_spectrum.png
```

The ends of the long lines are cut above. The latency line sums the declared latencies of the
fixed-latency blocks and notes that the PSD has none; the ingress line counts the stall cycles
that the overlap replay and the PSD readout imposed on the input.

The script asserts three properties: both tones are found in their exact bin; the max-hold
trace holds the chirp band at least 10 dB above the floor while the average smears it, by 13.4 dB in median here; the onset of the chirp is located
in absolute time, within one row.

The figure below is the waterfall. The two vertical stripes are the tones, the diagonal is the
chirp, and each row is labelled with the time core count of its first input sample.

![AN003 waterfall: Welch spectra over absolute time (time core count). Simulation.](ex_an003_waterfall.png){width=90%}

The figure below overlays the averaged spectrum and the max-hold trace: the chirp band stands
out in max-hold only.

![AN003 averaged spectrum and max-hold trace. Simulation.](ex_an003_spectrum.png){width=90%}

The input of the monitor, or any point of a chain, can also stream to a host over UDP; [Packets
and host links](#fe-packets) gives the wire format and the GNU Radio blocks that read it.

The blocks of the note are the time core, timestamper and untagger, the Welch PSD and its
window, FFT and PSD parts, and the peak-bin block, which would find the peak on chip; their
datasheets are in the [block
catalogue](https://github.com/enjoy-digital/litedsp/blob/main/doc/blocks/index.md).

## AN002: DQPSK modem and BER curve {#ex-an002}

This note closes the loop on a complete modem, transmitter, channel and receiver, and judges it
the way a modem is judged: BER against `Eb/N0`, compared with theory. It has two gates: an
implementation loss below 1 dB at a BER of `1e-3`, and one simulation point of the gateware that
agrees with the golden models.

### The chain {#ex-an002-chain}

The transmitter and the receiver are gateware; the channel is NumPy:

| Stage | Blocks | Role |
|---------------|----------------------------------------|---------------------------------------------|
| Transmitter | Differential encoder, symbol mapper | DQPSK phase steps, QPSK points |
| Transmitter | Pulse shaper | RRC interpolation, 2 samples per symbol |
| Channel | NumPy | 0.35-sample delay, 90 degree rotation, noise |
| Receiver | Complex FIR | Matched RRC filter |
| Receiver | Timing recovery | M&M loop, 2 samples per symbol to 1 |
| Receiver | Slicer, differential decoder | Decisions, phase steps back to bits |

The data rides on phase steps, Gray coded, so the 90 degree rotation of the channel is harmless:
the slicer decides in the rotated constellation and the differential decoder cancels the constant
offset. No carrier phase loop is needed. Carrier frequency recovery is out of the scope of the
note; a coherent receiver would add the carrier loop with the QPSK detector.

Timing recovery is real. The channel delays the signal by 0.35 sample, and the M&M loop acquires
and tracks it. During acquisition the loop can slip samples, so the bit counter aligns the
received and the sent symbols with a signed offset search after the acquisition transient.

### Model sweep and gateware point {#ex-an002-method}

A BER curve needs far more symbols than a Migen simulation can run in reasonable time. The sweep
therefore runs on the golden models, with one difference: the timing loop has no golden model, so
the model receiver samples at the known best instant.

One simulation point of the gateware closes the gap. Its transmitter waveform must equal the model's
exactly, and its BER, with the real M&M loop on the same noise, must be within three times the model
BER.

The theory curve is coherently detected, differentially encoded Gray QPSK:
`Pb = 2 Q (1 - Q)`, the bit error probability, with `Q = Q(sqrt(2 Eb/N0))`. It includes the doubling of errors of
differential decoding, not the larger loss of noncoherent DQPSK.

### Results {#ex-an002-results}

The output below comes from a run of the script, trimmed of its last line:

```console
$ python3 examples/qpsk_modem.py --plot-dir build/an002
DQPSK modem (AN002): RRC 2 sps -> AWGN -> matched filter -> M&M timing -> slicer -> diff decode
  model sweep (NumPy golden models):
    Eb/N0 4 dB: BER 2.58e-02 (39920 bits, theory 2.47e-02)
    Eb/N0 5 dB: BER 1.26e-02 (39920 bits, theory 1.18e-02)
    Eb/N0 6 dB: BER 4.53e-03 (79920 bits, theory 4.77e-03)
    Eb/N0 7 dB: BER 1.68e-03 (119920 bits, theory 1.54e-03)
    Eb/N0 8 dB: BER 3.75e-04 (239920 bits, theory 3.82e-04)
  Eb/N0 @ BER 1e-3: measured 7.35 dB, theory 7.33 dB, implementation loss 0.01 dB
  RTL point: Eb/N0 4 dB, 1500 symbols (Migen simulation of both chains)...
    RTL   BER 2.31e-02 (1904 bits)  [TX waveform == model: OK]
    model BER 1.64e-02 (1952 bits) on the same noisy waveform
  PASS: loss 0.01 dB < 1.0 dB @ BER 1e-3, RTL point consistent with model
[...]
```

The fixed-point modem, with Q1.15 RRC taps, a 16-bit datapath and hard decisions, costs almost
nothing at these points: 0.01 dB at the `1e-3` crossing, against a gate of 1 dB.

The gateware point with the real timing loop sits slightly above the model, which samples at the
ideal instant: the M&M loop adds timing jitter at 2 samples per symbol. The figure below plots the
sweep.

![AN002, simulation: BER of the DQPSK modem against Eb/N0. Compare the measured points of the
golden models with the theory curve; the single gateware point at 4 dB sits slightly above the
model.](ex_an002_ber.png){width=90%}

On hardware, the pattern source and the error counter would
generate and score the bits from the bus, after a frame synchronizer has aligned the stream.

## AN005: CCSDS concatenated FEC telemetry {#ex-an005}

This note builds the concatenated code of CCSDS 131.0-B space telemetry from LiteDSP blocks and
shows why it has an interleaver. A burst of channel errors that the chain cannot correct without
interleaving is corrected completely with it, because the deinterleaver spreads the bursty
Viterbi errors over several Reed-Solomon codewords ([Interleaving and concatenated
codes](#cpri-interleaving)).

### The chain {#ex-an005-chain}

| Stage | Block | Setting |
|---------------------|------------------------------|-------------------------------------------|
| Outer encoder | CCSDS RS encoder | RS(255,223), dual basis |
| Interleaver | Block interleaver | Depth `I` codewords of 255 bytes |
| Inner encoder | Convolutional encoder | K=7, generators 171 and 133, rate 1/2 |
| Modulation | Symbol mapper | QPSK, `g0` on I and `g1` on Q |
| Channel | NumPy | Noise at `Es/N0` 8 dB, plus a jamming burst |
| Soft demapping | Soft demapper | 4-bit LLRs |
| Inner decoder | Viterbi decoder | Soft, traceback 56 |
| Deinterleaver | Block deinterleaver | Inverse permutation |
| Outer decoder | CCSDS RS decoder | Up to 16 bytes per codeword |

The interleaver sits between the two codes and works on bytes, as CCSDS defines it. The `I`
codewords of a frame are written row by row, in the order a single RS encoder emits them, and sent
column by column: byte 0 of every codeword, then byte 1.

A burst of `B` channel bytes then lands as at most `ceil(B/I)` errors in each codeword, so the
correctable burst grows from 16 bytes to about `16 * I`.

### Simplifications {#ex-an005-limits}

The CCSDS classes use the field, the roots and the dual-basis representation of the standard, and
their parity matches an independent known-answer vector. The note interleaves at a depth of 2
where the blocks default to 5, serializes bytes LSB first where CCSDS sends MSB first (both ends
agree), has no sync marker or randomizer, and counts block boundaries from reset.

### The burst demonstration {#ex-an005-results}

The channel jams a run of QPSK symbols, inside the span of one codeword, with random constellation
points.

The script runs the same chain with and without the interleaver on the golden models, over several
burst lengths, then runs the whole chain in a Migen simulation, one block after another, passing
each captured stream to the next stage. The run takes a few minutes. The output below comes from
a run of the script; the long lines are cut with `[...]`:

```console
$ python3 examples/ccsds_telemetry.py --plot-dir build/an005
CCSDS telemetry (AN005): RS(255,223) x 2 -> interleave (I=2) [...]
  burst sweep (NumPy golden models, Es/N0 8 dB, [...]
[...]
    burst 120 syms: [...] 15 bytes OK             ILV worst  8 bytes OK
    burst 160 syms: [...] 20 bytes UNCORRECTABLE   ILV worst 10 bytes OK
[...]
    burst 240 syms: [...] 29 bytes UNCORRECTABLE   ILV worst 16 bytes OK
[...]
  correctable burst: 120 symbols plain -> 240 symbols interleaved [...]
  RTL end-to-end: I = 1 (223 message bytes), burst 60 symbols [...]
[...]
    message recovered error-free (223 bytes) in [...]
  PASS: burst of 160 symbols breaks the non-interleaved chain [...]
[...]
```

Read the 160-symbol line. Without interleaving, the burst puts 20 wrong bytes in one codeword, more
than the 16 the code corrects, and the message is lost; with a depth of 2, the same burst lands as
10 bytes in each of two codewords, and the message is recovered.

The correctable burst doubles, from 120 to 240 symbols, in line with the limit of `I * t = 32`
bytes. The figure below plots the sweep.

![AN005, simulation: worst number of wrong bytes per codeword against the burst length, with and
without interleaving. Look where each curve crosses the correction limit of 16 bytes.](ex_an005_burst.png){width=90%}

In the gateware run, the transmitter waveform, the LLRs and the Viterbi output equal their models,
and the message is recovered exactly. The default gateware point uses a depth of 1 and a 60-symbol
burst, which one codeword corrects.

`--rtl-depth 2` replays the 160-symbol burst through the interleaved chain. The example uses the register exchange Viterbi
architecture, which simulates faster than the decision memory one.

## AN006: ADS-B receiver {#ex-an006}

This note acquires an ADS-B extended squitter at 2 MHz, the usual minimum sample rate for it,
decodes its 112 pulse-position-modulated bits, parses the DF17 header and checks the Mode S
CRC-24. The correlator is gateware; the bit decisions and the parsing run on the host.

The Mode S preamble has pulses at 0, 1, 3.5 and 4.5 µs, which are the sample positions 0, 2, 7
and 9 at 2 MHz. The correlator uses a zero-mean 16-sample template of that preamble, which rejects
the DC level of the magnitude samples. After acquisition, each bit is decided by comparing the
energy of its early and late half.

The test frame is a DF17 message with the address `A5C33C` and an airborne position field, with
the 24-bit parity of the generator `0x1FFF409`. The script requires the exact preamble position,
no bit error, the exact fields, a zero CRC syndrome, the rejection of a frame with one flipped
bit, and a peak-to-sidelobe margin of at least 3 dB. A run prints:

```console
$ python3 examples/adsb_receiver.py --plot-dir build/an006
ADS-B receiver (AN006): preamble 24 (expected 24), correlation margin 3.1 dB, 0/112 bit errors, DF17 ICAO A5C33C TC11, CRC OK
PASS: RTL acquisition recovered and CRC-validated the complete DF17 frame
```

On hardware, a magnitude or power block goes in front of the correlator, and the detected sample
index can arm a capture block.

## AN007: AIS receiver {#ex-an007}

This note runs the receive side of an AIS modem at 9600 baud and four samples per symbol. AIS
uses GMSK with a BT of 0.4 and HDLC framing over NRZI, where a 0 is sent as a level change.

The script builds the transmitted packet on the host: a payload and its X.25 FCS between `0x7E`
flags, with bit stuffing, NRZI coded and GMSK modulated. It adds a carrier frequency offset and
noise, then streams the quantized I/Q through the FM discriminator in gateware.

The host then integrates each symbol at the ideal instant, removes the offset, decodes NRZI, finds
the 24-bit training sequence and the flags, removes the stuffed bits and checks the FCS.

The script requires the training sequence at the exact symbol, both flags, at least one stuffed
bit, a 96-bit payload without error, a valid FCS, the rejection of a corrupted payload, and a
minimum eye opening. A run prints:

```console
$ python3 examples/ais_receiver.py --plot-dir build/an007
AIS receiver (AN007): preamble symbol 12, flags 0/121, 1 stuffed bits, 0 payload bit errors, FCS OK, minimum eye 2566
PASS: RTL discriminator recovered and HDLC-deframed the complete AIS packet
```

Timing is ideal in this note. A free-running receiver adds the timing recovery block with the
Gardner detector, and the line decoder and HDLC deframer blocks do the NRZI and HDLC steps in
gateware, as [AN013](#ex-an013) shows.

## AN008: chirp spread-spectrum receiver {#ex-an008}

This note acquires a chirp spread-spectrum packet, in the style of LoRa, at spreading factor 7,
and recovers its symbols. Each symbol is a cyclic shift of a 128-sample up-chirp; multiplying by
the conjugate chirp (*dechirping*) turns it into a tone, whose FFT bin is the symbol value.

The packet has two noise-only blocks, six preamble up-chirps and four payload symbols, with a
carrier offset of 1.35 bins and noise.

The receiver first scans blocks for six consecutive dechirped spectra with the same peak, which
gives the packet start and the integer part of the offset. The CFO estimator block, with a delay of
128 samples, then measures the fractional part on the repeated preamble.

After the correction, the 128-point SDF FFT block gives the processing gain, and its bit-reversed
output is reordered on the host. The script requires the exact preamble block, the offset within
0.05 bin, all payload symbols, and a peak margin of at least 12 dB. A run prints:

```console
$ python3 examples/css_receiver.py --plot-dir build/an008
CSS receiver (AN008): SF7, preamble block 2, acquisition margin 4.2 dB, CFO 1.349 bins (truth 1.35, RTL fractional estimates [23164, 22596]), symbols [3, 17, 64, 109] -> [3, 17, 64, 109], minimum FFT margin 18.8 dB
PASS: acquired the CSS preamble, corrected RTL-estimated CFO, and decoded the packet
```

The note repeats each corrected payload block at the FFT input, only to avoid the fill ambiguity
of a standalone SDF pipeline; acquisition and offset estimation use the single received
preamble. A receiver entirely in gateware would generate the reference chirp with the chirp block
and dechirp with the mixer.

## AN013: GFSK, Hamming and HDLC text link {#ex-an013}

This note builds a complete low-rate data link from the communications blocks and checks it
against the golden models. A text message is framed, protected by a Hamming(7,4) code, GFSK
modulated, sent through noise, demodulated, decoded and deframed back to text, through the
chain of the table below.

| Stage | Block | Setting |
|--------------------|------------------------|------------------------------------------------|
| Framing | HDLC framer | Two opening flags, stuffing, X.25 FCS |
| Coding | Hamming encoder | (7,4) blocks, `m=3` |
| Modulation | FSK modulator | GFSK, BT 0.5, 8 samples per bit, index 1 |
| Channel | NumPy | Noise, one-symbol boxcar before detection |
| Demodulation | FM demodulator | Discriminator |
| Detection | NumPy | Timing from the opening flags, integrate and dump |
| Decoding | Hamming decoder | One error per block, counters |
| Deframing | HDLC deframer | Unstuffing, FCS check, `last` and `fcs_ok` |

### Results {#ex-an013-results}

The transmitter runs as one module whose blocks are built without registers; its I/Q output must
equal the composed models of the framer, the encoder and the modulator. The receiver blocks
decode three bit streams: the clean coded bits, one flipped bit per codeword, and two flipped
bits in one codeword. A run prints:

```console
$ python3 examples/fsk_hamming_link.py --plot-dir build/an013
[tx] 512 payload bits -> 552 framed -> 966 coded bits -> 7728 I/Q samples; bit-exact vs the models: True
[rx clean] fcs_ok 1, text matches
[rx 1 error / codeword] fcs_ok 1, text matches
[rx 2 errors in a codeword] fcs_ok 0, text differs
[ber] Eb/N0 dB     6     7     8     9    10    11
[ber] raw      0.058 0.043 0.028 0.011 0.008 0.007
[ber] coded    0.028 0.017 0.014 0.003 0.002 0.001
[rtl] raw BER at 8 dB 0.0404 (model 0.0276)
[...]
  PASS: waveform bit-exact, FEC and framing gates met
```

With one error per codeword, every block is corrected and the FCS passes; with two errors in one
codeword, the decoder counts one uncorrectable block and the FCS fails, as it must.

The BER curve is measured on the model chain with six noise draws per point. The gateware point
runs one more noisy waveform, at 8 dB, through the FM demodulator, and its raw BER must be within
a factor of three of the model average.

![AN013, simulation: raw and Hamming-coded BER of the GFSK link against Eb/N0, with the single
gateware point. Look at the gap between the two curves as the noise decreases.](ex_an013_fsk_hamming_link.png){width=90%}

The link needs no carrier recovery: an FSK discriminator ignores a carrier offset much smaller than
the deviation.

Hamming(7,4) corrects one error per block, so its gain appears once the raw BER is low enough; a BCH
decoder or an interleaver in front of it extends the corrected range at the cost of rate. The HDLC
deframer holds 24 bits back, so a frame aborted before that window fills produces no output.

Where to go next: [Benches](#boards) runs a chain on a board, [Integration](#integration) puts
one in a design, [Verification](#verification) explains how the examples are checked.
