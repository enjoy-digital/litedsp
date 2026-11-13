# Benches {#boards}

This chapter describes the two bench SoCs of `bench/`, which put a LiteDSP chain on a board with
nothing but LiteX, LiteX-Boards and a host bridge.

It gives what each bench contains, how to build it, how its host script checks it, and what the
repository records about it. Read it to bring up a chain on hardware or to start a bench for
another board.

## At a glance {#brd-glance}

| Bench | Boards | Clock | Host link | Chain |
|----------------------|------------------------|------------|----------------|----------------------------|
| `spectrum.py` | Arty, Colorlight 5A-75B | 100, 60 MHz | UARTBone | Tone, noise, DDC /8, capture |
| `stream.py` | Colorlight 5A-75B | 40 MHz | Etherbone, UDP | Tone, noise, DDC /64, UDP streamer |

Each bench has a host script of the same name with a `test_` prefix, in `bench/` too.

Both benches are `SoCMini` designs, without a CPU: the host reads and writes the registers
through the bridge with `litex_server`. Both make their own test signal on chip, a tone from an
NCO plus noise, so they need no converter and no signal generator.

The repository records builds of the benches, not runs on a board. The commit that added the
spectrum bench records that the Colorlight 5A-75B build went through place and route at 60 MHz
and produced a bitstream.

The commit that added the streaming bench records a build through place and route at 40 MHz,
with 46.9 MHz achieved. No sample rate, spectrum or error count measured on a board is recorded;
the status of the families is in [the status table](#intro-status).

CI elaborates both benches to Verilog on every push, for each supported board
(`.github/workflows/bench.yml`). This catches changes of the LiteX and LiteX-Boards interfaces
and of the register map, without running a vendor tool.

## Spectrum bench {#brd-spectrum}

The spectrum bench checks the generation, mixing, rate change and capture path over a serial
cable. The host tunes the test tone and the DDC, forces a capture, drains the captured buffer
and checks that the tone lands in the expected bin. The figure below shows the SoC.

![Spectrum bench. The NCO tone and the noise are added, down-converted and decimated by 8; the
capture block records the result, read back by the host over UARTBone, through its memory
window or the register reader.](brd_spectrum.svg)

The table below lists the blocks of `bench/spectrum.py` and their settings. The capture block
also exposes its buffer as a read-only memory window on the bus, at `0x30000000`, one sample per
32-bit word, which the host reads faster than through `LiteDSPCSRReader`.

| Instance | Block | Settings |
|-------------|----------------------------|-----------------------------------------------|
| `nco` | `LiteDSPNCO` | 16 bits, test tone |
| `noise` | `LiteDSPNoiseSource` | 16 bits, `shift=4` |
| `adder` | `LiteDSPIQAdd` | Tone plus noise |
| `ddc` | `LiteDSPDDC` | 16 bits, `decimation=8` |
| `capture` | `LiteDSPCapture` | `depth=2048` by default, Wishbone window |
| `reader` | `LiteDSPCSRReader` | Readout of the capture stream |

The SoC exports two constants for the host script, `SPECTRUM_CAPTURE_DEPTH` and
`SPECTRUM_DECIMATION`. The baseband sample rate is the system clock divided by the decimation:
12.5 MHz on the Arty at 100 MHz, 7.5 MHz on the Colorlight at 60 MHz.

### Boards {#brd-spectrum-boards}

The bench takes the platform and the clock generator of the LiteX-Boards target of each board.
The table below gives the board settings of the bench.

| Board | `--board` | Clock | Settings | Toolchain |
|------------------|-------------------------------|---------|---------------------|---------------|
| Arty | `arty` | 100 MHz | No DRAM, LED chaser | Vivado |
| Colorlight 5A-75B | `colorlight_5a_75b` | 60 MHz | No reset button, no LED | Yosys, nextpnr |

The LiteX-Boards targets are `digilent_arty` and `colorlight_5a_75x`.

On the Colorlight 5A-75B, the serial port of UARTBone shares its pins with the button and an
LED, so the bench uses neither. `--sys-clk-freq` overrides the system clock and
`--capture-depth` the capture depth; [Bench options](#opt-bench) lists every option.

### Build and test {#brd-spectrum-run}

```sh
# Build and load the bitstream (volatile)
python3 bench/spectrum.py --board=arty --build --load
python3 bench/spectrum.py --board=colorlight_5a_75b --build --load
# On the host: bridge, then the test
litex_server --uart --uart-port=/dev/ttyUSB0
python3 bench/test_spectrum.py --tone-freq=1e6 --tune-freq=1e6
```

`--load` loads the bitstream into the FPGA without writing the flash. The build writes `csr.csv`
in the current directory; the host script reads it and the two constants. Run the host script
from the directory of the build, or give it `--csr-csv`.

`bench/test_spectrum.py` sets the test tone to `--tone-freq` and the DDC oscillator to
`--tune-freq`, so the tone lands at their difference after down-conversion. It forces a capture,
reads the buffer through the memory window when the SoC has one and through `LiteDSPCSRReader`
otherwise, applies a Hann window and computes the spectrum.

**What to look for.** The script prints the SoC identifier with the clock, the capture depth and
the baseband rate, an ASCII spectrum, then the frequency of the peak and the expected one,
`--tone-freq` minus `--tune-freq`. It prints `PASS` when the peak is within two bins of the
expected frequency, `FAIL` otherwise.

With the default frequencies, the expected frequency is zero: the tone lands at DC. The peak
line shows where the tone landed.

## Streaming bench {#brd-stream}

The streaming bench sends the DDC output to the host as a continuous stream of UDP packets, over
the Gigabit Ethernet of the Colorlight 5A-75B. The same link carries Etherbone, so the host tunes
the tone and the DDC while the stream runs. The figure below shows the SoC.

![Streaming bench. The DDC output, decimated by 64, is packed into UDP packets that share the
Ethernet core with Etherbone, through which the host reaches the registers.](brd_stream.svg)

The chain is the one of the spectrum bench, with a decimation of 64 and no capture. The UDP
streamer packs one I/Q sample per 32-bit word, 256 samples per packet, and sends the packets to
the host address on port 6000 through the UDP core of Etherbone. The SoC exports
`STREAM_UDP_PORT`, `STREAM_DECIMATION` and `STREAM_SAMPLES_PER_PACKET`.

| Setting | Default | Option |
|--------------------|-------------------|-------------------|
| Board revision | `7.0` | `--revision` |
| SoC IP address | `192.168.1.50` | `--ip-address` |
| Host IP address | `192.168.1.100` | `--host-ip` |
| UDP port | 6000 | |
| Decimation | 64 | |
| Samples per packet | 256 | |
| System clock | 40 MHz | |

The system clock is set by the decimator: the decimation-64 CIC filter of the DDC has a 40-bit
integrator cascade, which bounds the clock on an ECP5 of speed grade 6. At 40 MHz, the baseband
rate is 625 kHz, 2.5 MB/s of samples on the link.

```sh
# Build and load the bitstream (volatile)
python3 bench/stream.py --build --load
# On the host: bridge, then the test
litex_server --udp --udp-ip=192.168.1.50 &
python3 bench/test_stream.py --tone-freq=1e6 --tune-freq=1e6
```

`bench/test_stream.py` tunes the tone and the DDC over Etherbone, closes the bridge session,
then listens on the UDP port and collects `--samples` samples, 65536 by default. It measures the
rate at which they arrive and computes their spectrum.

**What to look for.** The script prints the received sample count with the measured rate in
MS/s and as a percentage of the baseband rate, an ASCII spectrum, then the peak and the expected
frequency. It prints `PASS` when the peak is within 16 bins of the expected frequency. The rate
is timed from the first packet received, so it measures the sustained stream, not the start.

## Bringing up another board {#brd-port}

The benches select a board from a table in `bench/spectrum.py`: the LiteX-Boards platform and
target modules, the arguments of the target clock generator, the system clock and whether the
board has free LEDs. A board with a LiteX-Boards target and a serial port joins the spectrum
bench by adding one entry.

Start at a low system clock and check the timing report first: the DDC decimator limits the
frequency on small devices, as the streaming bench shows. [Debugging](#debugging) gives the
order of the checks once the bitstream is loaded: the bridge and the SoC identifier, then the
registers, then the captures.

Where to go next: [Integration](#integration) for a SoC of your own, [Debugging](#debugging) for
a bench that does not pass, [Build options](#opt-bench) for every bench option.
