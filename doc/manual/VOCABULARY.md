# Vocabulary of the LiteDSP manual

Project-specific writing rules, completing the generic `STYLE.md` of the manual kit.

## Names of the parts

- *LiteDSP* is the project and the `litedsp` package; never another name for it, and never the
  name of a predecessor design.
- *block* is one registry entry: a Migen module whose class name starts with `LiteDSP`
  (`LiteDSPMixer`, `LiteDSPFIRFilter`) and which has a datasheet in `doc/blocks/`. Not "IP",
  not "core", not "module" in prose.
- *composite* is a block built from other blocks (`LiteDSPDDC`, `LiteDSPDUC`, the FOC loop); its
  latency is the sum of the latencies of its stages.
- *family* is a registry category and its package directory: generation, mixing, correction,
  filter, rate, level, analysis, comm, stream, and in Part IV motor, audio, radar, image. Family
  names are written in lower case in prose. The frontend classes (`litedsp/frontend/`) follow the
  contract but are not a registry family.
- *parallel variant* is the N samples per clock version of a block (`LiteDSPParallelNCO`), bit
  identical to its serial counterpart. The z-parallel LDPC decoder is parallel inside only and
  keeps one LLR per beat: it is not a parallel variant.
- *chain* is a set of blocks connected by streams, in a SoC or built from a netlist.
- *netlist* is the JSON description of a chain read by the flow; *the flow* is `litedsp/flow/`
  (netlist, chain builder, delay balancer, IP packaging) and its tool `litedsp_flow`.
- *standalone core* is the Verilog core written by the generator from a YAML file; *the
  generator* is `litedsp_gen`. *The GUI* is `litedsp_gui`; *the drivers* are the host classes of
  `litedsp/software/drivers.py`; *the CLI* is `litedsp_cli`.
- *the registry* is `litedsp/flow/registry.py`, the list of all blocks, with the metadata
  reflected from each one (ports, registers, latency) used by the datasheet generator, the flow,
  the generator and the GUI.
- *frontend* is the converter and host-link side of a chain: ADC/DAC interfaces, I/Q packetizer,
  UDP I/Q streamer (`litedsp/frontend/`).

## Signal processing names

- *sample* is one value of the signal (one real value or one I/Q pair); *beat* is one stream
  transfer (`valid` and `ready` high in the same cycle); *lane* is one sample of a parallel beat:
  a beat of a parallel variant carries `n_samples` lanes.
- *sample rate* is the number of samples per second of the signal; *clock rate* is the frequency
  of the clock that runs the block. They differ whenever a block does not take a sample on every
  cycle.
- *latency* is counted in samples (beats): the `latency` attribute of a block, `None` when it is
  data dependent. Write "cycles" explicitly when a number counts clock cycles.
- *frame* is a group of beats delimited by `first` and `last`; *burst* is a radar frame (one
  pulse repetition interval or one coherent processing interval, as the radar chapter defines it).
- *bypass* is the `bypass` control of in-line blocks: the input passes unchanged, with the same
  latency as the processed path in the blocks built with `add_bypass`.
- Fixed-point formats are written Qm.n with a dot, `m` integer bits including the sign bit and
  `n` fractional bits: Q1.15, Q2.30. Not "Q15" in prose (`Q15` is a helper of `common.py`).
- *I/Q* with a slash for the complex baseband pair; `i` and `q` only as field names.
- Units: dB, dBFS, dBc, MHz, and MSPS (million samples per second) for sample rates.

## Verification names

- *golden model* is the NumPy reference of a block in `test/models.py`, bit identical to the
  gateware (170 of the 229 registry blocks have one); *co-simulation* is the Verilator run of the
  generated Verilog against the golden model (`sim/`).
- *budget* is a recorded result checked by CI: an implementation budget (`impl/budgets.json`,
  resources and fmax) or a characterization budget (`char/budgets.json`, SFDR, ENOB, ripple).
- *gate floor* is the lowest fmax CI accepts for a configuration (`fmax_min`, 85 % of the
  recorded fmax).
- *register* in prose, never "CSR", except in the bus name "CSR bus" and in class names
  (`CSRStorage`).
- Status words (Simulated, Synthesized, Implemented, Built for a board) are defined once, under
  the status table of the introduction ([status](#intro-status)); other chapters link to it.
- Characterization numbers are "measured on the golden models"; resource and fmax numbers are
  "out-of-context tool results".

## Placeholders

- `<block>` is a registry key or a block class; `<name>` is the `name` of a generator YAML file
  (the generator writes `<name>.v`); `<board>` is a bench board option (`arty`,
  `colorlight_5a_75b`). All three are defined once in the Conventions of the front matter.

## Hardware names

- Boards: Digilent Arty A7 (then "Arty"), Colorlight 5A-75B.
- FPGA families and devices: Lattice ECP5 (`LFE5UM5G-85F`), Xilinx Artix-7 (`xc7a200t`), Xilinx
  Artix UltraScale+ (`xcau20p`, written "AU+" in tables).
- Tools: Yosys, nextpnr, Vivado, Verilator, SymbiYosys.
