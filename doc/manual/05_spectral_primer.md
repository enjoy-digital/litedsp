# Oscillators, mixers and the FFT {#spectral-primer}

This chapter explains how a digital design makes a tone, moves a signal in frequency and looks
at its spectrum. It covers the numerically controlled oscillator and its spurs, the CORDIC,
complex mixing and the digital down- and up-converters, then the discrete Fourier transform, the
FFT, windows, power spectra and the Goertzel algorithm.

Each section ends with the LiteDSP blocks that implement the idea. [Generation, mixing and
correction](#generation-mixing) and [Level control and analysis](#level-analysis) describe those
blocks in detail.

## The NCO {#pri-nco}

A *numerically controlled oscillator* (NCO), also called a *direct digital synthesizer* (DDS),
generates a sine wave of programmable frequency. It keeps a *phase accumulator*, a register that
adds a constant, the *phase increment*, on every sample. The accumulator wraps around at its full
scale, which stands for one full turn, 2 pi. The figure below shows the structure.

![An NCO. The phase register adds phase_inc on every accepted sample and wraps on overflow; its
top bits address a cosine table and a sine table, which give the I and Q outputs.](pri_nco.svg)

With a phase accumulator of B bits, the output frequency is f = phase_inc fs / 2^B, where fs is
the sample rate. The frequency resolution is fs / 2^B: with B = 32 and fs = 100 MSPS, about
0.023 Hz. To produce 10 MHz at that rate, phase_inc = 2^32 x 10 / 100, rounded to 429496730.

The table lookup turns the phase into cos and sin. With both outputs, the NCO produces the
complex exponential e^(j 2 pi f n), a single line at +f (see [Real and complex
baseband](#pri-iq)). A phase increment above 2^(B-1) wraps to a negative value and gives a
negative frequency.

The NCO is a stream source. Its `valid` stays high once the first sample is ready, and the phase
only advances when a sample is accepted, so backpressure never skips or repeats a phase.

A sine has symmetries: one quarter of a period gives the other three by mirroring and negation. A
quarter-wave table of `lut_depth`/4 + 1 entries rebuilds cos and sin bit for bit, with about eight
times less memory than full cosine and sine tables. [NCO](#gm-nco) describes `LiteDSPNCO`, its
tables and its registers.

## Phase truncation and spurs {#pri-nco-spurs}

The table only sees the top bits of the phase: the lower bits are truncated. The truncation error
is not random. It repeats with a period set by the phase increment, so it modulates the output
and creates *spurs*, discrete lines beside the wanted tone. The worst spur drops by about 6 dB per
address bit of the table.

Some increments avoid the problem: when the low bits of phase_inc are zero, the phase always
lands exactly on a table entry. Only the amplitude quantization of the table then limits the
spectrum. The other increments are limited by phase truncation.

A deeper table pushes the spurs down by 6 dB per doubling; with a quarter-wave table, one four
times deeper still takes half the memory of the two full tables. Phase dithering, which spreads
the spurs into the noise floor, is not used. [NCO](#gm-nco) gives the measured SFDR, and
[Chirp](#gm-chirp) the chirp generator, an NCO whose frequency ramps.

## CORDIC {#pri-cordic}

The *CORDIC* algorithm rotates a vector with shifts and additions only. It decomposes any angle
into a sum of elementary angles atan(2^-i), i = 0, 1, 2 and so on; rotating by one of them only
needs a shift by i and an addition. Each iteration adds about one bit of precision.

In *rotation* mode, the CORDIC rotates a vector (x, y) by an angle z: starting from (1, 0), it gives
cos z and sin z. In *vectoring* mode, it rotates (x, y) onto the x axis and returns the angle it
needed, atan2(y, x), and the magnitude of the vector.

The iterations scale the vector by a constant gain K of about 1.65 (`cordic_gain` computes it),
which a final multiplication by 1/K removes.

`LiteDSPCORDIC` is a pipelined CORDIC in either mode, with the gain compensated
([CORDIC](#gm-cordic)).

## Complex mixing {#pri-mixing}

Multiplying a complex signal by the complex exponential e^(-j 2 pi f0 n) shifts its whole
spectrum by -f0: a tone at f0 lands at 0 Hz. Multiplying by e^(+j 2 pi f0 n) shifts it up. This is
*complex mixing*, and the exponential comes from an NCO, the *local oscillator* (LO).

The product of two complex numbers is (a + jb)(c + jd) = (ac - bd) + j(ad + bc): four real
multiplications and two additions. Shifting down uses the conjugate of the LO, c - jd, which only
changes the signs. Unlike a real mixer, a complex mixer creates no image: the spectrum moves as
one piece.

`LiteDSPMixer` multiplies its two inputs, in down or up mode set at run time
([Mixer](#gm-mixer)).

## DDC and DUC {#pri-ddc}

A *digital down-converter* (DDC) selects a narrow band out of a wide one and brings it to
baseband at a lower rate. It mixes the band down with an NCO, then decimates: the decimation
filter removes everything outside the band, and the lower rate suits the narrow band. The figure
below shows the structure.

![A digital down-converter. The mixer multiplies the input by the conjugate of the NCO output, so
the band at the NCO frequency lands at 0 Hz; the decimator then filters it and lowers the rate by
R.](pri_ddc.svg)

A *digital up-converter* (DUC) is the transmit mirror. It interpolates a baseband signal to a
high rate, then mixes it up to the NCO frequency. The interpolation comes first, so that the
mixer runs at the rate where the shifted band fits.

In LiteDSP the DDC mixes in down mode, the input times the conjugate of the NCO, so setting the
NCO `phase_inc` to the frequency of the band, f_tune 2^32 / fs with the default 32-bit phase,
brings that band to 0 Hz. [DDC](#gm-ddc) and [DUC](#gm-duc) describe both blocks.

The CIC decimator of a DDC droops in its passband (see [CIC filters](#pri-cic)). A chain that needs
a flat band adds a compensation FIR after it. A bank of DDCs tuned to equally spaced frequencies
is a *channelizer*; a polyphase filter bank shares one filter and one DFT between all channels
([Channelizer](#gm-channelizer)).

## The discrete Fourier transform {#pri-dft}

The *discrete Fourier transform* (DFT) turns a frame of N samples into N frequency *bins*. Bin k
measures how much of the frequency k fs / N the frame contains: X[k] is the sum over n of
x[n] e^(-j 2 pi k n / N). The bins are spaced by fs / N, the *frequency resolution* of the
transform.

For a complex input the N bins cover the whole band from -fs/2 to +fs/2. Bins 0 to N/2 - 1 hold
the positive frequencies, and bins N/2 to N - 1 the negative ones, in the same order as they wrap
around. A direct DFT costs N^2 complex multiplications per frame.

## The FFT {#pri-fft}

The *fast Fourier transform* (FFT) computes the same N bins with about (N/2) log2 N complex
multiplications. The radix-2 FFT splits a transform of N points into two of N/2, recursively, until
it reaches transforms of 2 points.

Each split combines pairs of values in a *butterfly*: a sum, a difference, and a multiplication of
the difference by a *twiddle factor*, e^(-j 2 pi p / N).

A radix-2 FFT has log2 N stages of butterflies. Each stage can double the magnitude of the
values, so an N-point FFT can grow by log2 N bits. A fixed-point FFT either halves the values at
each stage, giving an output of DFT / N, or tracks the growth per frame with a shared exponent:
*block floating point*.

A hardware FFT can be *streaming*, accepting one sample per clock on and on, or *iterative*, storing
a frame in memory and computing it in place. The *single-path delay-feedback* (SDF) architecture is
the classic streaming one.

Each stage has one butterfly and a delay line of D samples that holds the first half of each block
while the second half arrives, as the figure below shows.

![A radix-2 SDF FFT. The stages run in a row, the delay of stage k being N / 2^(k+1): N/2, N/4,
down to 1 for the last stage. Inside a stage the butterfly works with its delay-feedback memory
and a twiddle multiplier; the output comes out in bit-reversed order.](pri_sdf.svg)

LiteDSP has both kinds, a streaming SDF FFT with plain or block floating-point scaling and an
iterative one in block RAM; [FFT](#ana-fft) lists the engines.

## Bit reversal {#pri-bitrev}

A decimation-in-frequency FFT produces its bins in *bit-reversed* order: the bin whose index is
written b2 b1 b0 in binary comes out in position b0 b1 b2. For N = 8, the bins come out in the
order 0, 4, 2, 6, 1, 5, 3, 7. Putting them back in natural order needs a memory of one frame.

A ping-pong memory of two frames does it on a stream: each frame is written at bit-reversed
addresses while the other one is read in order ([Bit reversal](#ana-bitrev)).

## Windows and leakage {#pri-window}

The DFT treats each frame as one period of a periodic signal. A tone that does not complete a
whole number of periods in the frame has a jump at the frame boundary, and its energy spreads
over all the bins: this is *leakage*. A strong tone can then hide a weak one many bins away.

A *window* multiplies the frame by a curve that tapers to zero at both ends, removing the jump.
Leakage falls far away from the tone, at the cost of a wider peak around it. The table below
compares the windows of LiteDSP, from the narrowest peak to the lowest leakage.

| Window | Main lobe | Sidelobes | Use |
|-------------|------------|---------------------------|----------------------------------------|
| `rect` | Narrowest | Highest | Tones on bin centres, transients |
| `hann` | Wider | Low, falls fast | General spectrum analysis (default) |
| `hamming` | Same as Hann | Lowest first sidelobe, falls slowly | Close tones of similar level |
| `blackman` | Widest | Lowest | Weak tones next to strong ones |

`LiteDSPWindow` applies a window fixed at build time to frames of `n` samples
([Window](#ana-window)).

## Power spectral density and Welch {#pri-psd}

The *power spectrum* of a frame is the squared magnitude of each bin, I^2 + Q^2. Computed on one
frame of noise, it fluctuates strongly from bin to bin. Averaging the power spectra of many
frames reduces that variance and gives a smooth estimate of the *power spectral density* (PSD).

The *Welch* method windows each frame before the FFT, then averages. Windowing tapers the frame
ends, so the samples there count less; overlapping consecutive frames, typically by 50 %, uses
them again and recovers that loss from the same amount of input.

`LiteDSPPSD` averages the power of each bin over a number of FFT frames, or holds its maximum
or minimum, and `LiteDSPWelchPSD` adds the window and the overlap ([PSD](#ana-psd)). The spectrum
monitor of [Examples](#examples) uses it.

## Goertzel {#pri-goertzel}

When only a few bins are needed, a full FFT is wasted work. The *Goertzel* algorithm computes a
single DFT bin with a second-order resonator: s[n] = x[n] + c s[n-1] - s[n-2], with c = 2 cos(2 pi k
/ N).

After N samples, the power of bin k is s1^2 + s2^2 - c s1 s2, where s1 and s2 are the last two
states.

The resonator needs one multiplication per sample, so detecting a few tones, such as the DTMF
tones of a telephone keypad or a pilot tone, costs a few multipliers instead of an FFT.

`LiteDSPGoertzel` detects one bin and emits its power every N samples
([Goertzel](#ana-goertzel)).

Where to go next: [Digital communications](#comm-primer) for modulation and coding,
[Generation, mixing and correction](#generation-mixing) and [Level control and
analysis](#level-analysis) for the blocks of this chapter.
