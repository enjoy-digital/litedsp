```{=latex}
\frontmatter
```

# About this document {.unnumbered}

This manual is the reference of LiteDSP: a library of fixed-point signal processing blocks for
FPGAs, written in Migen and LiteX, with the tools that turn chains of blocks into Verilog. It is
written for FPGA engineers who want to reuse the blocks, and it teaches the signal processing
along the way.

No prior knowledge of digital signal processing is assumed. The manual has four parts, Understand,
The core, Use it and Application families, plus appendices; [How to read this
manual](#intro-reading) maps them and sends each question to its chapter.

The manual follows the repository: names, numbers and defaults are taken from the source code,
and the register, build-option and performance appendices are generated from it.

When the code and the manual disagree, the code is right and the manual has a bug. The block
datasheets of `doc/blocks/` stay the online catalogue; the manual explains the blocks and links to
them.

## Conventions {.unnumbered}

- Numbers: `0x` prefix for hexadecimal, `0b` for binary.
- Fixed-point formats are written Qm.n: `m` integer bits including the sign bit, `n` fractional
  bits. Q1.15 is a 16-bit sample in the range [-1, 1).
- Rates: sample rates in MSPS (million samples per second), clock rates in MHz. Levels in dB,
  dBFS (relative to full scale) and dBc (relative to a carrier).
- Latencies are counted in samples, that is in stream beats, unless the text says cycles.
- *A block* is an entry of the registry, a class whose name starts with `LiteDSP`; *a chain* is a
  set of blocks connected by streams; *a register* is a register of the SoC bus, never called CSR
  in the text.
- `<block>` stands for a registry key or a block class, such as `fir_real` or `LiteDSPNCO`;
  `<name>` stands for the `name` of a generator YAML file, whose Verilog output is `<name>.v`;
  `<board>` stands for a bench board option, `arty` or `colorlight_5a_75b`.
- Paths are relative to the repository root. Shell commands are given for a Linux host.
- Numbers measured on the golden models and out-of-context tool results are labelled as such;
  the [Status](#intro-status) section says how far each family has been taken.
- When the text names a source file, it is the file to open to check or extend the fact.
