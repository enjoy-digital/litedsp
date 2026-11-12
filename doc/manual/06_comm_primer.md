# Digital communications {#comm-primer}

This chapter explains how bits travel over a radio or cable link, for an FPGA engineer who knows
sampled signals but not modems. It follows the path of the data: modulation, symbols and pulses,
the synchronization a receiver needs, the codes that frame and protect the bits, OFDM, and how a
link is measured.

It builds on the complex baseband of [Sampled signals and fixed point](#dsp-primer), the filters
of [Digital filters](#filter-primer) and the NCO, mixer and FFT of [Oscillators, mixers and the
FFT](#spectral-primer). [Communications blocks](#comm) maps each concept to the LiteDSP blocks
that implement it.

## From bits to a signal {#cpri-modem}

A digital link turns bits into a waveform, sends it through a channel, and turns the received
waveform back into bits. The channel adds noise, attenuates and delays the signal, shifts its
frequency, and on a radio link adds echoes. The receiver must undo all of it from the received
samples alone.

The figure below shows the parts of a modem. The transmitter groups bits into *symbols*, maps
each symbol to a point of a constellation, and shapes each point into a pulse a few samples
long. The receiver filters the samples, finds the carrier phase and the symbol instants, then
decides which point was sent.

![A digital modem. Follow the data from the bits of the transmitter, through the channel, to the
decisions of the receiver. The cyan blocks of the receiver are the synchronization work that the
transmitter does not have to do. The channel box also stands for the RF parts and the
converters.](pri_modem.svg)

The *symbol rate* is the number of symbols per second; the *bit rate* is the symbol rate times
the bits per symbol. A receiver usually runs at two or more samples per symbol (*sps*): enough
samples to see where a symbol starts and ends, not only its value.

## Analog modulations {#cpri-analog}

The oldest modulations change one property of a carrier with a message signal. In complex
baseband the carrier is removed, and the property is the magnitude, the phase or the rate of
change of the phase of the I/Q sample.

| Modulation | Message changes | Baseband form | Simple demodulator |
|--------------|------------------------|----------------------------|-------------------------------|
| AM | Envelope | `1 + m x` | Magnitude, then remove DC |
| PM | Phase | `exp(j k x)` | Angle of the sample |
| FM | Frequency | `exp(j k sum(x))` | Angle of `x[n] conj(x[n-1])` |
| SSB | One sideband only | `x + j hilbert(x)` | Coherent mixing |

In the table, `x` is the message, `m` the AM modulation index and `k` the PM or FM deviation.
The FM discriminator multiplies each sample by the conjugate of the previous one. The angle of
that product is the phase step between the two samples, which is the instantaneous frequency, so
no phase unwrapping is needed.

*Frequency-shift keying* (FSK) is FM with a message that takes a few discrete levels, one per
symbol. The *modulation index* `h` is the tone spacing divided by the symbol rate. MSK is binary
FSK with `h = 0.5`. GMSK and GFSK smooth the frequency steps with a Gaussian filter, whose
bandwidth-time product BT sets how smooth the transitions are.

LiteDSP implements AM, FM, PM, SSB and FSK modulators, FM and AM demodulators and a phase
detector as blocks ([Modulators and demodulators](#comm-modem)).

## Constellations and Gray coding {#cpri-constellations}

Digital modulations send one point of a *constellation* per symbol. A point is a complex number:
its magnitude and phase, or equivalently its I and Q coordinates, carry the bits. The receiver
measures the received point and picks the closest constellation point.

| Name | Bits per symbol | Points | Placement |
|----------|-----------------|--------|---------------------------------------|
| BPSK | 1 | 2 | Two phases, 180 degrees apart |
| QPSK | 2 | 4 | Four phases, one per quadrant |
| 16-QAM | 4 | 16 | Square grid, 4 levels on I and on Q |
| 64-QAM | 6 | 64 | Square grid, 8 levels on I and on Q |

A square QAM constellation is two independent PAM signals, one on I and one on Q. With `L` levels
per axis, the levels sit at `(2k - (L - 1)) * spacing` for `k` from 0 to `L - 1`: odd multiples of
`spacing`.

The decision boundaries between levels sit at even multiples of `spacing`. The LiteDSP mapper,
slicer and soft demapper all use this convention.

*Gray coding* labels the points so that neighbours differ in one bit. Noise usually moves a point
to a neighbour, so a symbol error then costs one bit error, not several. The Gray code of a
binary index `b` is `b ^ (b >> 1)`.

Some receivers do not know the absolute carrier phase: a QPSK receiver that locks on the wrong
quadrant rotates every point by 90 degrees.

*Differential encoding* sends the difference between consecutive symbol indices, modulo the number
of points, so a constant rotation cancels. The cost is about twice the bit errors, since one wrong
symbol spoils two differences. DBPSK and DQPSK use it.

## Pulse shaping and matched filtering {#cpri-pulse}

A symbol cannot be sent as a single sample, because a sharp step has a wide spectrum. The
transmitter filters the symbol stream with a *pulse shaping* filter that limits the bandwidth. The
pulses spread over several symbol periods and overlap. The overlap must vanish at the symbol
instants, or each decision sees its neighbours: *inter-symbol interference* (ISI).

The *raised cosine* pulse is zero at every symbol instant except its own centre. Its bandwidth is
`(1 + beta) / 2` times the symbol rate, where the *roll-off* `beta` is between 0 and 1. A smaller
roll-off uses less bandwidth but needs a longer filter and more precise timing.

The receiver also filters, to remove the noise outside the signal band. The best receive filter
for white noise is the *matched filter*: the time-reversed conjugate of the transmit pulse. Links
therefore split the raised cosine into two *root raised cosine* (RRC) filters, one in each end.
Their cascade is the raised cosine, with no ISI at the sampling instants.

LiteDSP provides the transmit RRC interpolator as a filter block and computes RRC and Gaussian
taps with the filter design helpers; [Digital filters](#filter-primer) explains FIR filters and
interpolators.

## Symbol timing recovery {#cpri-timing}

The receiver samples with its own clock, which is neither aligned with the symbol instants nor
exactly at the transmitter's rate. *Timing recovery* estimates where the symbol centres are,
interpolates the signal there, and follows the drift between the two clocks.

An *interpolation controller* keeps two numbers: `omega`, the estimated samples per symbol, and
`mu`, the fractional position of the next symbol centre between two input samples. A fractional
delay filter, such as a cubic [Farrow interpolator](#pri-farrow), computes the sample at `mu`.
Each symbol, `mu` advances by `omega`, and its integer part says how many input samples to
consume.

A *timing error detector* (TED) measures whether the interpolated point is early or late. A
second-order loop turns the error into corrections of `mu` (proportional path) and `omega`
(integral path). Two detectors are common:

- *Mueller and Muller* (M&M) uses the decisions on the current and the previous symbol. It needs
  one sample per symbol, but it assumes the carrier is locked, since it relies on decisions.
- *Gardner* uses two symbols and the sample half-way between them. It needs two samples per
  symbol and works before carrier lock, since it uses no decisions.

## Carrier recovery {#cpri-carrier}

The local oscillator of the receiver is never exactly at the transmitter's frequency. The
difference, the *carrier frequency offset* (CFO), makes the constellation spin; a fixed phase
difference rotates it by a constant angle. *Carrier recovery* removes both by multiplying the
samples by a correcting complex exponential.

A *phase-locked loop* (PLL) does this with an NCO. A *phase detector* measures the phase error of
each sample, and a proportional-integral (PI) loop filter turns it into an NCO frequency. The NCO
phase derotates the next samples: the integral path learns the frequency offset, the
proportional path corrects the phase. The phase detector depends on the signal:

| Signal | Phase detector | Lock points |
|--------------------------|-------------------------------|-------------|
| Residual carrier (tone) | `Q` of the derotated sample | 1 |
| BPSK (Costas loop) | `sign(I) * Q` | 2 |
| QPSK (decision directed) | `sign(I) * Q - sign(Q) * I` | 4 |

A loop that uses decisions locks with an ambiguity: a QPSK loop is equally stable at each of the
four quadrants. Differential encoding or a known preamble resolves it.

A PI loop only pulls in a small offset, so a burst receiver first estimates the offset from a
repeated signal.

If the signal repeats every `D` samples, the product `x[n] * conj(x[n - D])` has the phase `2 pi f
D` whatever the data, where `f` is the offset in cycles per sample. Averaging the products and
taking the angle gives `f`, without ambiguity while `|f| < 1/(2D)`.

Repeated preambles and the cyclic prefix of OFDM provide such a repetition; the Schmidl and Cox
and the van de Beek estimators are built on it.

## Frame synchronization {#cpri-frame-sync}

A receiver must also find where a packet starts. The transmitter sends a known *preamble* (also
called a sync word or attached sync marker) first. The receiver correlates the incoming samples
with it, through a matched filter whose taps are the conjugated, time-reversed preamble. The
output peaks when the preamble is aligned with the filter.

A good preamble has a sharp autocorrelation: a high peak and low sidelobes. Barker codes are
short binary codes whose sidelobes have a magnitude of one at most; longer preambles use
pseudo-noise (PN) sequences.

A fixed threshold on the peak fails when the signal level changes. A *normalized* detector
compares the squared correlation with the energy of the same window of samples. The ratio is 1
for a perfect match, whatever the gain, and about `1/N` for noise over an `N`-sample preamble.

## Hard and soft decisions {#cpri-decisions}

A *slicer* makes a *hard decision*: it returns the closest constellation point and its bits. It
throws away how sure it was, so a sample right on a decision boundary and a sample right on a
point give the same bits.

A *soft decision* keeps that information as a *log-likelihood ratio* (LLR) per bit: the logarithm
of the probability that the bit is 0 over the probability that it is 1. Its sign is the hard
decision, its magnitude the confidence. A decoder fed with LLRs needs a lower signal-to-noise
ratio than one fed with hard bits for the same error rate.

The *max-log* approximation computes LLRs from the distances to the closest point of each
hypothesis. For Gray-coded square QAM it reduces to piecewise-linear functions of each axis
value: no division and no logarithm. The LLRs are then scaled by the inverse of the noise
variance and quantized to a few bits.

## Line codes, scrambling and framing {#cpri-bit-coding}

A *line code* shapes the bit stream for the medium. NRZI sends a bit as the presence or absence of a
level change, so the receiver does not need to know the polarity.

Manchester sends each bit as two chips with a transition in the middle. It guarantees transitions
for clock recovery and removes DC, at the cost of twice the chip rate.

A *scrambler* makes the bit stream look random, so that long runs of ones or zeros disappear and the
spectrum is flat.

A *multiplicative* scrambler XORs each bit with earlier output bits at the polynomial taps; its
descrambler XORs with earlier input bits at the same taps. The descrambler synchronizes by itself,
but one channel bit error becomes one error plus one more per feedback tap: three errors for
the default polynomial 1 + x^18 + x^23.

A *cyclic redundancy check* (CRC) detects errors. The transmitter appends the remainder of the
division of the message by a generator polynomial, and the receiver checks the remainder of the
whole frame. CRC-16-CCITT uses the polynomial `x^16 + x^12 + x^5 + 1`.

*HDLC framing* delimits frames on a bit stream with the flag `0x7E` (`01111110`). To keep the flag
unique, the transmitter inserts a 0 after five consecutive ones (*bit stuffing*), and the
receiver removes it. The frame ends with a 16-bit frame check sequence, the X.25 CRC. AX.25 and
the AIS ship identification system use HDLC over NRZI.

## Forward error correction {#cpri-fec}

*Forward error correction* (FEC) adds redundancy so that the receiver corrects errors without
asking for a retransmission. A code maps `k` message symbols to `n` coded symbols; its *rate* is
`k/n`. The *minimum distance* `d` is the smallest number of positions in which two codewords
differ, and a code corrects up to `(d - 1)/2` errors per codeword.

### Block codes {#cpri-block-codes}

A *block code* encodes fixed-size blocks independently. *Systematic* codes send the message
unchanged and append the parity, which keeps the encoder a division circuit.

| Code | Symbols | Example | Corrects |
|-----------------------|---------|-------------|--------------------------------|
| Hamming | Bits | (7,4) | 1 bit per block |
| Extended Hamming | Bits | (8,4) | 1 bit, detects 2 (SECDED) |
| BCH | Bits | (15,7) | `t` bits per block, here 2 |
| Reed-Solomon | Bytes | (255,223) | `(n - k)/2` bytes, here 16 |

A Hamming decoder computes the *syndrome*, the parity check of the received block; a non-zero
syndrome names the wrong bit. BCH and Reed-Solomon (RS) codes are built on a finite field GF(2^m).

They decode in three steps: compute `2t` syndromes, find the *error locator* polynomial with the
Berlekamp-Massey algorithm, then find its roots by trying every position (*Chien search*).
Reed-Solomon also needs the error values, which the *Forney* formula gives.

Reed-Solomon codes work on symbols of `m` bits: bytes for RS(255,223). A burst of bit errors
inside one byte costs a single symbol, so RS codes resist bursts well. RS(255,223) corrects 16
wrong bytes in each 255-byte codeword.

### Convolutional codes and the Viterbi decoder {#cpri-conv}

A *convolutional encoder* is a shift register of the `K - 1` previous bits, where `K` is the
*constraint length*.

Each input bit produces `n` output bits, each the XOR of the input and the register bits selected by
a generator polynomial, written in octal. The K=7 code with generators 171 and 133 is the rate-1/2
code of CCSDS telemetry, DVB-S and 802.11a.

The register contents are the encoder's *state*, one of `2^(K-1)`. A *trellis* draws the states
at each time step and the transitions between them, as the figure below shows for `K = 3`. Each
state has two outgoing branches, one per input bit, and two incoming branches.

![One step of the trellis of the K=3, rate-1/2 code with generators 7 and 5. Solid branches carry
input 0, dotted branches input 1; each branch is labelled with its two coded bits. Look at state
00 at time n+1: it can be reached from 00 or from 01, and the decoder keeps only the more likely
of the two cyan branches.](pri_trellis.svg)

The *Viterbi decoder* finds the most likely path through the trellis. For each state it keeps a
*path metric*: the distance between the received sequence and the best path ending there. Each
step, it computes the *branch metrics*, adds them to the path metrics of the two predecessors of
each state, compares the sums and keeps the smaller: *add-compare-select* (ACS).

The decoder records which branch won at each state: the *survivors*. Following them backwards
from the best state, the *traceback*, gives the decoded bits. The survivor paths merge after a
few constraint lengths, so a traceback depth of five to eight times `K` loses almost nothing; the
decoding delay is that depth.

With hard decisions, the branch metric is the Hamming distance between the received bits and the
expected ones. With soft decisions, it is the sum of the LLR magnitudes whose sign disagrees with
the expected bits; the rest of the decoder is the same.

*Puncturing* raises the rate of a code by not sending some coded bits, following a fixed pattern.
The rate-1/2 mother code gives the rates 2/3, 3/4, 5/6 and 7/8 with the patterns of DVB-S (ETSI
EN 300 421). The receiver reinserts an LLR of 0, an *erasure*, at each dropped position, so one
Viterbi decoder serves every rate.

### LDPC codes {#cpri-ldpc}

A *low-density parity-check* (LDPC) code is defined by a sparse parity-check matrix `H`: each row
is one parity check over a few code bits. Its decoder passes messages between the bit nodes and
the check nodes of the graph of `H` for a few iterations, and stops when every check is
satisfied.

The *min-sum* decoder simplifies the check node update. The magnitude it sends to a bit is the
minimum of the magnitudes of the other bits of the check, and the sign is the product of their
signs.

Scaling that minimum by a factor below one (*normalized min-sum*) recovers most of the loss of the
simplification. A *layered* schedule updates the bit values after each group of checks, which
converges in fewer iterations.

*Quasi-cyclic* LDPC codes, such as the codes of 802.11n, build `H` from a small *base matrix*
whose entries are `z` by `z` cyclically shifted identity matrices. The *lifting size* `z` lets a
decoder process `z` checks in parallel, with a rotation in front of them.

### Interleaving and concatenated codes {#cpri-interleaving}

Decoders correct scattered errors better than bursts. An *interleaver* reorders symbols before the
channel so that a burst on the channel becomes scattered errors after the deinterleaver. A *block
interleaver* writes a matrix row by row and reads it column by column. A *convolutional* (Forney)
interleaver delays each branch by a different multiple of a depth, with less memory.

A *concatenated* code chains two codes, as the figure below shows. The inner convolutional code
faces the noisy channel. When it fails, it produces bursts of errors, which the deinterleaver
spreads over several Reed-Solomon codewords. With an interleaving depth `I`, bursts of up to about
`I * t` bytes are corrected. CCSDS 131.0-B defines this chain for space telemetry.

![A concatenated FEC chain. Read each decoder under its encoder: the receiver undoes the
transmitter in reverse order. The LLRs of the demodulator feed the Viterbi decoder, which passes
hard bytes to the Reed-Solomon decoder.](pri_fec_chain.svg)

## OFDM {#cpri-ofdm}

*Orthogonal frequency-division multiplexing* (OFDM) sends many slow symbols in parallel on
closely spaced subcarriers, instead of one fast symbol stream. The transmitter places one
constellation point per subcarrier, or *bin*, and runs an inverse FFT of size `N`; the receiver
runs an FFT to get the bins back. A multipath channel only scales and rotates each narrow
subcarrier.

The transmitter copies the last samples of each OFDM symbol in front of it: the *cyclic prefix*
(CP). While the channel echoes are shorter than the prefix, they stay within one symbol, and the
FFT sees a circular convolution. The channel then multiplies bin `k` by one complex number `H_k`,
which the receiver removes with a *one-tap equalizer* per bin.

The receiver learns `H_k` from a known training symbol. The *least-squares* (LS) estimate is the
received bin divided by the known bin; with a QPSK training symbol, a multiplication by the
conjugate of the reference, up to a constant. The squared magnitude
`|H_k|^2`, the *channel state information* (CSI), tells the soft demapper how much to trust each
bin.

![An OFDM link. Follow a block of N bins: the inverse FFT makes N samples, the cyclic prefix makes
CP + N, and the receiver removes the prefix, runs the FFT and equalizes each bin before the
demapper.](pri_ofdm.svg)

## Measuring a link {#cpri-ber}

The *bit error rate* (BER) is the fraction of wrong bits; the *symbol error rate* (SER) counts
wrong symbols. Both are plotted against the signal-to-noise ratio, as a *waterfall curve*.

Links are compared at equal energy per information bit: `Eb/N0`, the energy per bit over the noise
spectral density. The energy per symbol is `Es = Eb * bits_per_symbol * code_rate`, so `Es/N0` in dB
is `Eb/N0` plus `10 log10(bits_per_symbol * code_rate)`.

Gray-coded QPSK in white noise has `BER = Q(sqrt(2 Eb/N0))`, the same as BPSK, where `Q` is the tail
of the normal distribution.

The *implementation loss* of a receiver is how much more `Eb/N0` it needs than theory for the same
BER, often read at a BER of `1e-3`.

The *coding gain* of a code is how much less `Eb/N0` the coded link needs than the uncoded one at
the same BER. A BER point is only meaningful once enough errors have been counted, so low BER points
need long runs.

On hardware, a pseudo-random bit sequence (PRBS) generator feeds the transmitter, and an error
counter compares the received bits with the same sequence. LiteDSP has both as blocks, the
pattern source and the error counter. Its application notes measure BER on the golden models and
check one point in a simulation of the gateware ([Examples and application notes](#examples)).

## Where to go next {#cpri-next}

[Communications blocks](#comm) describes the LiteDSP blocks of each concept of this chapter;
[Examples and application notes](#examples) assembles them into complete links.
