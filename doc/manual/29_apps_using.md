# Using the application families {#apps-using}

This chapter shows how to put the blocks of the four application families to work: as standalone
cores generated from a YAML file, as blocks in a LiteX SoC, and from the host through the typed
drivers. It ends with the examples and application notes of each family and how to run them.

The generator, the netlist format and the host software of all blocks are in [Flow, generator,
GUI and host software](#tooling); this chapter covers what is particular to these families.

The cores and examples are in `examples/`, the drivers in `litedsp/software/drivers.py`; the
development status of each family is in the [status table](#intro-status).

## Standalone cores {#apps-cores}

`litedsp_gen` turns a YAML file into a standalone Verilog core with AXI-Stream data ports, an
AXI-Lite register port and a register map ([Flow, generator, GUI and host software](#tooling)).
Three YAML files of `examples/` build cores from the application families.

| File | Chain | Input layout | Output layout |
|--------------------------|---------------------------------------------|--------------|----------------|
| `foc_core.yml` | FOC current controller | `abc`, `angle` | `abc` |
| `audio_core.yml` | 3-band EQ, compressor, volume, 16-bit dither | `tdm` | `tdm` |
| `image_core.yml` | Debayer, white-balance gain, RGB to YCbCr | `pixel` | `pixel_rgb` |

The pin-level blocks of the families are not inside these cores: the PWM drives gate signals, and
the I2S and PDM converters drive and sample audio pins. They have no stream on one side, so they
sit next to the core, in the user's design or in a LiteX SoC. The figure below shows the two
arrangements.

![Standalone cores and their pin-level neighbours. The FOC core takes currents and an angle and
feeds a PWM generator next to it; the audio core sits between an I2S receiver and an I2S
transmitter. The host reaches the registers of the cores over AXI-Lite and those of the
neighbours over the bus of the design.](apps_cores.svg)

### The FOC core {#apps-foc-core}

The FOC core has two AXI-Stream inputs, the measured phase currents and the rotor electrical
angle, and one output, the three phase duties. The controller's setpoints, gains, limit and
open-loop bring-up vector are AXI-Lite registers. The YAML file is short:

```yaml
name     : foc_core
csr_base : 0x0

flow:
  name       : foc
  data_width : 16
  clock_ns   : 10.0
  inputs     : [{id: i_abc, layout: abc}, {id: angle, layout: angle}]
  outputs    : [{id: duty,  layout: abc}]
  blocks:
    - {id: foc, type: foc, params: {}}
  connections:
    - {from: i_abc,      to: foc.sink}
    - {from: angle,      to: foc.sink_angle}
    - {from: foc.source, to: duty}
```

Generating it needs no vendor tool. The run below wrote its files to a scratch directory, shown
here as `build/foc`:

```console
$ litedsp_gen examples/foc_core.yml --output-dir build/foc
Generated: build/foc/foc_core.v
           build/foc/csr.csv
           build/foc/csr.json
           build/foc/csr.h
           build/foc/blocks.json
CSR banks:
  0x00000000: foc
```

The Verilog module has the stream ports `i_abc_*`, `angle_*` and `duty_*` (valid, ready, first,
last, payload), the AXI-Lite port `s_axil_*`, and `sys_clk` and `sys_rst`. The register map in
`csr.csv` starts with the controller registers of [The FOC composite](#mot-foc):

```text
csr_register,foc_dq_setpoint_d,0x00000000,1,rw
csr_register,foc_dq_setpoint_q,0x00000004,1,rw
[...]
csr_register,foc_svpwm_control,0x00000034,1,rw
```

The duties feed a `LiteDSPPWM` instantiated next to the core, whose acceptance of one sample per
period paces the core ([The loop is paced by the PWM](#mot-paced)). The currents and the angle
come from the ADC interface and the position decoder of the design.

### The audio core {#apps-audio-core}

The audio core takes and returns a channel-tagged TDM stream of 24-bit Q1.23 samples, left 0 and
right 1. The chain is the EQ, the compressor, the volume and a 16-bit dither with second-order
shaping (`shaping: ef2`). The generator gives each block its own register bank:

```console
$ litedsp_gen examples/audio_core.yml --output-dir build/audio
Generated: build/audio/audio_core.v
[...]
CSR banks:
  0x00000000: comp
  0x00000800: dither
  0x00001000: eq
  0x00001800: vol
```

The output directory also holds the memory initialization files (`.init`) of the block memories,
which the console output does not list. The I2S or PDM converters sit next to the core ([Converters
and clocking](#aud-converters)); the `sys_clk` of the core must meet the cycle budget of its serial
engines ([Two engine styles](#aud-engines)).

### The image core {#apps-image-core}

The image core takes raw RGGB Bayer pixels, 8-bit codes framed by `first`, `eol` and `last`, and
returns BT.601 YCbCr pixels. The chain is a bilinear demosaic, a per-channel gain for white
balance and a colour matrix; the line buffer inside the demosaic is sized for 640-pixel lines.

```console
$ litedsp_gen examples/image_core.yml --output-dir build/image
[...]
CSR banks:
  0x00000000: csc
  0x00000800: demosaic
  0x00001000: wb
```

The blocks are described in [Image blocks](#image).

### Radar and sonar chains {#apps-radar-chains}

There is no YAML core for the radar family: a chain of bursts and several stream kinds
([Radar and sonar blocks](#radar)) is built as a flow netlist or directly in a LiteX SoC, as the
application notes do in simulation.

## Blocks in a LiteX SoC {#apps-soc}

Inside a LiteX SoC, the blocks are instantiated directly, as in [Integration](#integration). The
attribute name becomes the register prefix: a `LiteDSPFOC` added as `self.foc` exposes
`foc_dq_setpoint_d` and the other registers in the SoC's `csr.csv`.

```python
from litedsp.motor import LiteDSPFOC, LiteDSPPWM

# FOC current controller feeding the PWM, which paces it.
self.foc = LiteDSPFOC()
self.pwm = LiteDSPPWM(with_irq=True)
self.comb += self.foc.source.connect(self.pwm.sink)

# Gate signals to the pads; over-current comparator to the fault input.
self.comb += [
    pads.pwm_h.eq(self.pwm.pwm_h),
    pads.pwm_l.eq(self.pwm.pwm_l),
    self.pwm.fault.eq(pads.fault),
]
```

The pad names are those of the user's platform; the currents and the angle connect to
`self.foc.sink` and `self.foc.sink_angle` ([Motor control blocks](#motor)).

## Host drivers {#apps-drivers}

A driver binds to the registers of one block instance by its prefix, through any bus object that
exposes `bus.regs` with `read()` and `write()`. A LiteX `RemoteClient` connected to `litex_server`
is the usual one. The constructor is `Driver(bus, prefix, clk_freq=None)`; `clk_freq` is needed by
the drivers that convert hertz or seconds into cycles.

```python
from litex import RemoteClient
from litedsp.software.drivers import FOCDriver, PWMDriver

bus = RemoteClient()
bus.open()
pwm = PWMDriver(bus, "pwm", clk_freq=100e6)
pwm.set_frequency(20e3)
pwm.set_dead_time(500e-9)
foc = FOCDriver(bus, "foc")
foc.set_gains(kp=1.5, ki=0.0125)
foc.set_open_loop(True, v_q=0.1)
pwm.enable()
```

The prefixes and the numbers in the sketch are examples: the prefix is the name of the block in
the SoC, and the gains are those of the AN009 motor model ([Models and loops](#mot-an009-models)).
A real motor gets its own from the per-unit design of [Layouts and conventions](#mot-conventions).

`discover(bus, clk_freq, manifest)` instantiates a driver for every block of a register map. With
the `blocks.json` manifest that `litedsp_gen` writes next to `csr.csv`, the match is exact: each
instance gets its typed driver, or a generic driver reflected from the registry. The manifest of
the audio core, for example, maps each prefix to a registry key:

```json
{
  "comp": "compressor",
  "dither": "dither",
  "eq": "audio_eq",
  "vol": "volume"
}
```

The typed drivers of each family are listed in its chapter: [motor](#mot-host),
[audio](#aud-host), [radar and sonar](#rad-host) and [image](#img-host).

Blocks without a typed driver are still reachable through the generic driver of `discover()`, or
through the raw registers listed in the [register appendix](#registers).

## Examples and application notes {#apps-examples}

Each family has at least one example script in `examples/` that builds a chain of RTL blocks,
runs it in Migen simulation against NumPy models and prints the gates it checks. The table below
lists them; each application note is folded into its family chapter, with its results.

| Example | Note | Chain | Results in |
|------------------------------------------------|---------|-------------------------------|--------------------------------|
| `foc_pmsm.py` | AN009 | FOC and PWM on a per-unit PMSM; ideal, encoder and sensorless angle | [AN009](#mot-an009) |
| `audio_processor.py` | AN010 | EQ, dynamics, volume, meter, dither and the I2S transport, in three passes | [AN010](#aud-an010) |
| `chirp_radar.py` | AN004 | Chirp, complex matched filter, magnitude | [AN004](#rad-an004) |
| `pulse_doppler_radar.py` | AN011 | Range gate, compression, MTI, Doppler, CFAR, tracker | [AN011](#rad-an011) |
| `image_pipeline.py` | AN012 | Debayer, gain, colour matrix, edge branch, histograms | [AN012](#img-an012) |

Every example ends with `PASS` when its gates hold; the results are simulation results. The
`--plot-dir` option writes the figures of the application note to a directory. Two examples,
`foc_pmsm.py` and `chirp_radar.py`, default it to the committed figures of `doc/app_notes/` and
rewrite them; pass `--plot-dir` to keep the checkout clean. The others plot only when it is given.
The examples are run by the CI examples job (`test/test_examples.py`), with matplotlib on the Agg
backend.

```sh
python3 examples/foc_pmsm.py --plot-dir /tmp/apps
python3 examples/audio_processor.py --plot-dir /tmp/apps
python3 examples/chirp_radar.py --plot-dir /tmp/apps
python3 examples/pulse_doppler_radar.py --plot-dir /tmp/apps
python3 examples/image_pipeline.py --plot-dir /tmp/apps
```

Where to go next: [Integration](#integration), [Verification](#verification) and the [register
appendix](#registers).
