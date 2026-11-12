```{=latex}
\part{Use it}
```

```{=html}
<h1 class="part">Part III. Use it</h1>
```

# Getting started {#getting-started}

This chapter takes you from a fresh machine to a first chain that runs in simulation and to a
standalone core generated from a YAML file. It needs no board and no FPGA tool. Each step gives
the command, what you should see, and what to check when you do not.

## Prerequisites {#gs-install}

LiteDSP is a Python package built on Migen and LiteX. Install LiteX by following the
installation page of its wiki; it installs Migen, LiteX and the other cores. Then install
LiteDSP from a clone of its repository, in development mode:

```sh
git clone https://github.com/enjoy-digital/litedsp
cd litedsp
pip3 install -e .
```

`pip3 install -e .` also installs NumPy and PyYAML. CI tests the package with Python 3.9 and
3.11. The other tools depend on what you run, as the table below shows.

| Task | Tools |
|------------------------------------|------------------------------------------------------|
| Unit tests, examples | Python 3, Matplotlib for the plots (optional) |
| Co-simulation and lint | Verilator |
| Flow editor | DearPyGui (`pip3 install -e .[gui]`) |
| ECP5 implementation, Colorlight | Yosys, nextpnr and Trellis |
| Artix-7 and Artix UltraScale+ | Vivado |
| Benches | LiteX-Boards; LiteEth for the streaming bench |

## Step 1: check the installation {#gs-check}

The unit tests compare the blocks with their NumPy golden models in Migen simulation, under
random backpressure. The whole suite is long, as CI runs it in shards; one test module is enough to
check the installation. The NCO module below checks bit exactness and spectral purity.

```console
$ python3 -m unittest test.test_nco -v
test_bit_exact (test.test_nco.TestNCO) ... ok
test_quarter_wave_bit_exact (test.test_nco.TestNCO) ... ok
test_spectral_purity (test.test_nco.TestNCO) ... ok

----------------------------------------------------------------------
Ran 3 tests in 2.670s

OK
```

**What you should see.** Three tests pass. The full suite runs with
`python3 -m unittest discover -s test -v`; [Verification](#verification) describes it and the
Verilator co-simulation.

**If not.** An import error names the missing package: `migen` or `litex` for the LiteX
installation, `numpy` for NumPy. A failure inside a test is a real mismatch between a block and
its model; [Debugging](#debugging) explains how to look at it.

## Step 2: simulate a first chain {#gs-chain}

`examples/ddc_chain.py` builds a digital down-converter from four blocks and runs it in the
stream simulator of the tests. The local oscillator, an NCO, is tuned to an eighth of the sample
rate; the mixer shifts the input down by that frequency; a 33-tap FIR filter removes what lies
outside the band; the downsampler keeps one sample in four.

![The first chain. Two NumPy tones enter the mixer; the NCO tone at fs/8 shifts them down; the
FIR filter and the downsampler produce a stream at fs/4, captured back into
NumPy.](gs_ddc_chain.svg)

The example wires the blocks itself, without registers: each block is built with
`with_csr=False` and its control signals are driven directly, which is how composites wire their
sub-blocks. The connections are plain `connect()` calls between `source` and `sink` endpoints.

```python
self.nco   = LiteDSPNCO(data_width=data_width, with_csr=False)
self.mixer = LiteDSPMixer(data_width=data_width, with_csr=False)
self.fir   = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=data_width,
    coefficients=coefficients, with_csr=False)
self.deci  = LiteDSPDownsampler(data_width=data_width, with_csr=False)

self.comb += [
    self.nco.phase_inc.eq(lo_phase_inc),
    self.mixer.mode.eq(MIXER_MODE_DOWN),
    self.deci.factor.eq(decimation),
    self.sink.connect(self.mixer.sink_a),
    self.nco.source.connect(self.mixer.sink_b),
    self.mixer.source.connect(self.fir.sink),
    self.fir.source.connect(self.deci.sink),
    self.deci.source.connect(self.source),
]
```

The input holds two complex tones of amplitude 12000, one at an eighth and one at three eighths
of the sample rate. `run_stream()` of `test/common.py` drives the 4096 input samples into the
`sink`, collects the outputs from the `source`, and the script skips the first 33 outputs, the
filling of the filter.

```console
$ python3 examples/ddc_chain.py
DDC output: 991 samples @ fs/4
  DC (down-converted tone) magnitude :  11981.2
  residual AC (rejected tone) std    :      0.0
  rejection                          :  261.6 dB
```

**What you should see.** The wanted tone lands at DC with about its input amplitude. The
second tone falls at a quarter of the sample rate after the mixer, a frequency the decimation by
four folds onto DC as well. Its residue therefore adds to the DC line instead of the
fluctuation, which is zero; the printed rejection is the floor of the script's division, not a
measurement.

**If not.** A run that hangs is a stream that stopped: a block upstream never asserts `valid`
or a block downstream never asserts `ready`. [Debugging](#debugging) lists the usual causes.

## Step 3: generate a standalone core {#gs-gen}

`litedsp_gen` builds the same kind of chain from a YAML file and wraps it as a Verilog core with
AXI-Stream data ports and an AXI-Lite control port, without any vendor tool.
`examples/ddc_core.yml` describes a DDC with an NCO, a delay, a mixer, a pipelined 33-tap FIR
filter and a downsampler ([Generator configuration](#tool-gen) shows the file).

```console
$ python3 -m litedsp.gen examples/ddc_core.yml
Generated: [...]/build/ddc_core.v
           [...]/build/csr.csv
           [...]/build/csr.json
           [...]/build/csr.h
           [...]/build/blocks.json
CSR banks:
  0x00000000: deci
  0x00000800: lo
  0x00001000: lpf
  0x00001800: mix
```

`litedsp_gen examples/ddc_core.yml` is the same command through the console script. The output
directory is `build/` by default; `--output-dir` changes it.

**What you should see.** The core and its register map land in `build/`, with the NCO table
files `cos_rom.init` and `sin_rom.init`. Each block with registers has a bank, 2 KiB apart; the
delay `dly` has none. The register map starts as below.

```console
$ grep csr_register build/csr.csv | head -4
csr_register,deci_factor,0x00000000,1,rw
csr_register,lo_phase_inc,0x00000800,1,rw
csr_register,lpf_coeffs_coeff_0,0x00001000,1,rw
csr_register,lpf_coeffs_coeff_1,0x00001004,1,rw
```

The FIR filter has one register per coefficient, `lpf_coeffs_coeff_0` to `lpf_coeffs_coeff_32`,
then `lpf_bypass`; the mixer has `mix_control`. The module `ddc_core` has the ports `rx_in_*`
and `bb_out_*` for the streams, `s_axil_*` for the registers, and `sys_clk` and `sys_rst`.

**If not.** `Config must provide exactly one of 'flow' (inline) or 'netlist' (path)` means the
YAML file has both or neither. A netlist error lists every problem it found, with the block id
and port; [Validation](#tool-validation) lists the rules.

## Step 4: go further {#gs-next}

The table below gives the chapter for each next step.

| Goal | Chapter |
|----------------------------------------------|--------------------------------------------|
| Put blocks or a netlist in a LiteX SoC | [Integration](#integration) |
| Put the standalone core in a Vivado design | [Vivado packaging](#tool-vivado) |
| Build a bench SoC for an Arty or a Colorlight | [Benches](#boards) |
| Run a larger chain in simulation | [Examples](#examples) |
| Draw a chain in the editor | [Flow editor](#tool-gui) |
