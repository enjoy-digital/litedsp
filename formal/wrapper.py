#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Emit per-block formal-verification tops for SymbiYosys (reuses litedsp/verilog.py).

For each registry entry this generates, into a build directory:

- ``<name>.v``         — the block converted to Verilog exactly like sim/impl do
  (:func:`litedsp.flow.generate.emit_verilog`), at a tiny config (data_width=4).
- ``<name>_formal.sv`` — a generated top that drives every sink (valid/first/last/payload) and
  every source ready with free ``(* anyseq *)`` inputs, applies the reset at cycle 0, ties the
  runtime controls (factor/sel/enable), and binds the ``formal/stream_props.sv`` checkers:
  stream stability (assumed on sinks, asserted on sources), weighted token conservation
  (no loss / no duplication under arbitrary backpressure) and no valid-from-nowhere.

Scope: formal owns the *plumbing* (handshake-heavy, low-arithmetic blocks); the numerics are
owned by the Verilator co-sim (``sim/``). The per-block bounds/weights are documented in
``doc/formal.md``.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.flow.generate import emit_verilog

from litedsp.stream.buffer  import LiteDSPSkidBuffer
from litedsp.stream.fifo    import LiteDSPStreamFIFO
from litedsp.stream.delay   import LiteDSPDelay
from litedsp.stream.split   import LiteDSPSplit
from litedsp.stream.combine import LiteDSPCombine
from litedsp.stream.route   import LiteDSPChannelMux, LiteDSPChannelDemux
from litedsp.stream.adapt   import LiteDSPIQClockDomainCrossing, LiteDSPIQPack, LiteDSPIQUnpack
from litedsp.rate.dropper   import LiteDSPDownsampler, LiteDSPUpsampler

DATA_WIDTH = 4  # Tiny payload: the properties are payload-width-agnostic, small keeps BMC fast.

# Endpoint helpers ---------------------------------------------------------------------------------

def _fields(ep):
    """(name, width) payload fields of a stream Endpoint."""
    out = []
    for name, shape in ep.description.payload_layout:
        out.append((name, shape[0] if isinstance(shape, tuple) else shape))
    return out

def _pin(ep, prefix):
    """Pin deterministic Verilog port names on an anonymous (list-held) endpoint.

    Endpoints held in a *list* attribute are anonymous to Migen's tracer (ports would come out
    as ``valid``, ``valid_1``, ...), so they get pinned to the named-attribute convention
    (``<prefix>_valid`` / ``<prefix>_payload_<f>``) — same trick as ``sim/run_blocks.py``.
    """
    for attr in ("valid", "ready", "first", "last"):
        getattr(ep, attr).name_override = f"{prefix}_{attr}"
    for f, _ in _fields(ep):
        getattr(ep, f).name_override = f"{prefix}_payload_{f}"
    return ep

# Registry -----------------------------------------------------------------------------------------

def _spec(dut, sinks, sources,
    in_weight      = 1,      # Weight added to f_diff per input transfer.
    out_weight     = 1,      # Weight subtracted from f_diff per output transfer.
    min_diff       = 0,      # No-duplication bound (exact).
    max_diff       = 0,      # No-loss bound: declared latency + internal buffering (+ margin).
    spurious       = False,  # Registered-output block: source valid low until 1st sink transfer.
    ties           = (),     # ((port, width, value), ...) control inputs tied to constants.
    consts         = (),     # (port, ...) control inputs driven (* anyconst *) (stable, arbitrary).
    tie_first_last = False,  # Tie sink first/last low (packet framing out of scope, see doc).
    cover_stall    = True,   # Cover a source stall (valid && !ready) to de-vacuate stability.
    extra          = (),     # Raw extra assertion lines (lockstep, unselected-channel quiet).
    mode           = "bmc",  # "prove" where k-induction closes, else "bmc" (see run_formal.py).
    ):
    return {
        "dut"            : dut,
        "sinks"          : sinks,   # ((prefix, endpoint), ...)
        "sources"        : sources, # ((prefix, endpoint), ...)
        "in_weight"      : in_weight,
        "out_weight"     : out_weight,
        "min_diff"       : min_diff,
        "max_diff"       : max_diff,
        "spurious"       : spurious,
        "ties"           : tuple(ties),
        "consts"         : tuple(consts),
        "tie_first_last" : tie_first_last,
        "cover_stall"    : cover_stall,
        "extra"          : tuple(extra),
        "mode"           : mode,
    }

def skid_buffer():
    # stream.Buffer(pipe_valid + pipe_ready): 1 pipe register + 1 skid register = 2 in flight.
    d = LiteDSPSkidBuffer(data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        max_diff=2, spurious=True)

def stream_fifo():
    # SyncFIFO depth=2: at most 2 accepted-but-not-yet-delivered samples.
    d = LiteDSPStreamFIFO(depth=2, data_width=DATA_WIDTH, with_csr=False)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        max_diff=2, spurious=True)

def delay_d1():
    # depth=1 shifts valid alone (regressed once: empty v_pipe[:-1] slice) — kept as own entry.
    d = LiteDSPDelay(depth=1, data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        max_diff=1, spurious=True)

def delay_d2():
    d = LiteDSPDelay(depth=2, data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        max_diff=2, spurious=True)

def split():
    # Atomic comb fan-out: both sources transfer exactly when the sink does (f_diff pinned to 0).
    # Note: gates valid on all-ready (valid depends on ready), so a source-side stall with valid
    # high is unreachable by construction — cover_stall is off (stability is vacuous here).
    d = LiteDSPSplit(n=2, data_width=DATA_WIDTH)
    for k, s in enumerate(d.sources):
        _pin(s, f"sources{k}")
    return _spec(d, [("sink", d.sink)],
        [(f"sources{k}", s) for k, s in enumerate(d.sources)],
        cover_stall=False, mode="prove",
        extra=(
            "// Lockstep fan-out: both sources see exactly the same transfers.",
            "always @(*) if (!rst) assert ((sources0_valid && sources0_ready)"
            " == (sources1_valid && sources1_ready));",
        ))

def combine():
    # Synchronous join, 1 output register: both sinks consumed together, f_diff in [0, 1].
    d = LiteDSPCombine(n_channels=2, data_width=DATA_WIDTH, with_csr=False)
    for k, s in enumerate(d.sinks):
        _pin(s, f"sinks{k}")
    return _spec(d, [(f"sinks{k}", s) for k, s in enumerate(d.sinks)],
        [("source", d.source)],
        max_diff=1, spurious=True,
        ties=[("enable", 2, 0b11)],  # All channels enabled (enable shapes payload, not handshake).
        extra=(
            "// Lockstep join: both sinks are consumed together.",
            "always @(*) if (!rst) assert ((sinks0_valid && sinks0_ready)"
            " == (sinks1_valid && sinks1_ready));",
        ))

def channel_mux():
    # Comb routing; sel is (* anyconst *): arbitrary but stable (switching mid-stream is not a
    # stability-preserving operation and is out of scope, see doc/formal.md).
    d = LiteDSPChannelMux(n=2, data_width=DATA_WIDTH, with_csr=False)
    for k, s in enumerate(d.sinks):
        _pin(s, f"sinks{k}")
    return _spec(d, [(f"sinks{k}", s) for k, s in enumerate(d.sinks)],
        [("source", d.source)],
        consts=("sel",), mode="prove",
        extra=(
            "// Unselected sink is backpressured, never drained.",
            "always @(*) if (!rst && (sel == 1'd0)) assert (!sinks1_ready);",
            "always @(*) if (!rst && (sel == 1'd1)) assert (!sinks0_ready);",
        ))

def channel_demux():
    d = LiteDSPChannelDemux(n=2, data_width=DATA_WIDTH, with_csr=False)
    for k, s in enumerate(d.sources):
        _pin(s, f"sources{k}")
    return _spec(d, [("sink", d.sink)],
        [(f"sources{k}", s) for k, s in enumerate(d.sources)],
        consts=("sel",), mode="prove",
        extra=(
            "// Unselected source stays quiet (no duplication to the other channel).",
            "always @(*) if (!rst && (sel == 1'd0)) assert (!sources1_valid);",
            "always @(*) if (!rst && (sel == 1'd1)) assert (!sources0_valid);",
        ))

def cdc():
    # Same-domain LiteX ClockDomainCrossing degenerates to a pure comb passthrough (documented
    # honest scope: the async-FIFO path is multi-clock and not covered by this single-clock setup).
    d = LiteDSPIQClockDomainCrossing(cd_from="sys", cd_to="sys", data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)], mode="prove")

def iq_pack():
    # 2 samples -> 1 word (LiteX _UpConverter): word register + 1 partial slot, f_diff in [0, 2].
    # sink first/last tied low: on last the converter emits a *partial* word (packet semantics),
    # which breaks sample accounting — framing is out of scope for the sample-stream fabric.
    d = LiteDSPIQPack(ratio=2, data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        in_weight=1, out_weight=2, max_diff=2, spurious=True, tie_first_last=True)

def iq_unpack():
    # 1 word -> 2 samples (LiteX _DownConverter, comb): the first sample of a word transfers
    # *before* the word itself is consumed, so f_diff dips to -(ratio-1) by construction.
    d = LiteDSPIQUnpack(ratio=2, data_width=DATA_WIDTH)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        in_weight=2, out_weight=1, min_diff=-1, max_diff=0)

def downsampler():
    # factor tied to 2: keep 1 of 2. The kept sample is the *first* of its group, so one output
    # may precede its group's dropped sample (f_diff = -1); dropped samples consumed while the
    # output stalls push f_diff up to +2.
    d = LiteDSPDownsampler(data_width=DATA_WIDTH, factor_bits=4, with_csr=False)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        in_weight=1, out_weight=2, min_diff=-1, max_diff=2, spurious=True,
        ties=[("factor", 4, 2)])

def upsampler():
    # factor tied to 2: emit 2 per input (sample-and-hold), f_diff in [0, 2].
    d = LiteDSPUpsampler(data_width=DATA_WIDTH, factor_bits=4, with_csr=False)
    return _spec(d, [("sink", d.sink)], [("source", d.source)],
        in_weight=2, out_weight=1, max_diff=2, spurious=True,
        ties=[("factor", 4, 2)])

REGISTRY = {
    "skid_buffer"   : skid_buffer,
    "stream_fifo"   : stream_fifo,
    "delay_d1"      : delay_d1,
    "delay_d2"      : delay_d2,
    "split"         : split,
    "combine"       : combine,
    "channel_mux"   : channel_mux,
    "channel_demux" : channel_demux,
    "cdc"           : cdc,
    "iq_pack"       : iq_pack,
    "iq_unpack"     : iq_unpack,
    "downsampler"   : downsampler,
    "upsampler"     : upsampler,
}

# Formal top generation ----------------------------------------------------------------------------

def _port_dirs(verilog_path):
    """Port directions of the emitted Verilog top: {port: "input"|"output"}.

    Migen derives IO directions from usage, so a source-side signal the block never drives
    (e.g. delay/combine drop ``first``/``last`` — sample streams carry no framing) comes out as
    an *input*. Those must be tied low in the formal top and excluded from the stability
    contract, or the solver would drive them as free variables and "fail" the DUT.
    """
    dirs = {}
    with open(verilog_path) as f:
        for line in f:
            m = re.match(r"\s*(input|output)\s+(?:signed\s+)?(?:\[[^\]]+\]\s*)?(\w+),?\s*$", line)
            if m:
                dirs[m.group(2)] = m.group(1)
            elif dirs and ");" in line:
                break
    return dirs

def _undriven(prefix, ep, dirs):
    """Source-side flag/payload ports the block leaves undriven (emitted as inputs)."""
    names = [f"{prefix}_first", f"{prefix}_last"]
    names += [f"{prefix}_payload_{f}" for f, _ in _fields(ep)]
    return {n for n in names if dirs.get(n) == "input"}

def _endpoint_wires(prefix, ep, is_sink, tie_first_last, undriven=frozenset()):
    """Wire declarations for one endpoint (anyseq on the environment-driven side)."""
    anyseq = "(* anyseq *) "
    lines  = []
    if is_sink:
        lines.append(f"{anyseq}wire {prefix}_valid;")
        if tie_first_last:
            lines.append(f"wire {prefix}_first = 1'b0;")
            lines.append(f"wire {prefix}_last  = 1'b0;")
        else:
            lines.append(f"{anyseq}wire {prefix}_first;")
            lines.append(f"{anyseq}wire {prefix}_last;")
        for f, w in _fields(ep):
            lines.append(f"{anyseq}wire [{w-1}:0] {prefix}_payload_{f};")
        lines.append(f"wire {prefix}_ready;")
    else:
        lines.append(f"{anyseq}wire {prefix}_ready;")
        lines.append(f"wire {prefix}_valid;")
        for n, w in [(f"{prefix}_first", 1), (f"{prefix}_last", 1)] + \
                    [(f"{prefix}_payload_{f}", w) for f, w in _fields(ep)]:
            rng = "" if w == 1 else f"[{w-1}:0] "
            if n in undriven:  # Not driven by the block: tie low (see _port_dirs).
                lines.append(f"wire {rng}{n} = {w}'d0;")
            else:
                lines.append(f"wire {rng}{n};")
    return lines

def _stability(prefix, ep, is_sink, undriven=frozenset()):
    """One stream_stability instance (assumed on sinks, asserted on sources)."""
    widths = dict([(f"{prefix}_first", 1), (f"{prefix}_last", 1)] +
                  [(f"{prefix}_payload_{f}", w) for f, w in _fields(ep)])
    vec    = [v for v in widths if v not in undriven]
    width  = sum(widths[v] for v in vec)
    return (f"stream_stability #(.WIDTH({width}), .ASSUME({1 if is_sink else 0})) "
            f"f_stability_{prefix} (\n"
            f"        .clk(clk), .rst(rst),\n"
            f"        .valid({prefix}_valid), .ready({prefix}_ready),\n"
            f"        .payload({{{', '.join(vec)}}})\n"
            f"    );")

def emit_formal_top(name, spec, path, dirs):
    """Write the generated ``<name>_formal.sv`` top for ``spec`` to ``path``.

    ``dirs`` is the emitted Verilog's port-direction map (:func:`_port_dirs`): source-side
    flags/payloads the block leaves undriven are tied low and dropped from the stability vector.
    """
    sinks, sources = spec["sinks"], spec["sources"]
    undriven = {prefix: _undriven(prefix, ep, dirs) for prefix, ep in sources}
    lines = [
        "//",
        f"// {name}_formal — generated by formal/wrapper.py, do not edit.",
        "//",
        f"module {name}_formal (",
        "    input wire clk",
        ");",
        "",
        "    // Reset: asserted at cycle 0 only (standard sby setup).",
        "    reg f_past_valid = 1'b0;",
        "    always @(posedge clk) f_past_valid <= 1'b1;",
        "    wire rst = ~f_past_valid;",
        "",
        "    // Environment: free (anyseq) producers/consumers, quiet during reset.",
    ]
    for prefix, ep in sinks:
        lines += ["    " + l for l in _endpoint_wires(prefix, ep, True, spec["tie_first_last"])]
    for prefix, ep in sources:
        lines += ["    " + l for l in _endpoint_wires(prefix, ep, False, False, undriven[prefix])]
    for prefix, _ in sinks:
        lines.append(f"    always @(*) if (rst) assume (!{prefix}_valid);")

    # Controls: build-time-fixed ties + stable-but-arbitrary (anyconst) selections.
    if spec["ties"] or spec["consts"]:
        lines.append("")
        lines.append("    // Controls.")
        for port, width, value in spec["ties"]:
            lines.append(f"    wire [{width-1}:0] {port} = {width}'d{value};")
        for port in spec["consts"]:
            lines.append(f"    (* anyconst *) wire {port};")

    # DUT.
    conns = [".sys_clk (clk)", ".sys_rst (rst)"]
    for prefix, ep in sinks + sources:
        for attr in ("valid", "ready", "first", "last"):
            conns.append(f".{prefix}_{attr}({prefix}_{attr})")
        for f, _ in _fields(ep):
            conns.append(f".{prefix}_payload_{f}({prefix}_payload_{f})")
    for port, _, _ in spec["ties"]:
        conns.append(f".{port}({port})")
    for port in spec["consts"]:
        conns.append(f".{port}({port})")
    lines += ["", "    // DUT.", f"    {name} dut ("]
    lines += [f"        {c}," for c in conns[:-1]] + [f"        {conns[-1]}", "    );"]

    # Stream contract: assumed on the driven sinks, asserted on the DUT sources.
    lines += ["", "    // Stream contract: stability assumed on sinks, asserted on sources."]
    for prefix, ep in sinks:
        lines.append("    " + _stability(prefix, ep, True))
    for prefix, ep in sources:
        lines.append("    " + _stability(prefix, ep, False, undriven[prefix]))

    # Token conservation.
    in_tx  = " || ".join(f"({p}_valid && {p}_ready)" for p, _ in sinks)
    out_tx = " || ".join(f"({p}_valid && {p}_ready)" for p, _ in sources)
    any_sv = " || ".join(f"{p}_valid" for p, _ in sources)
    lines += [
        "",
        "    // Token conservation (no loss / no duplication).",
        f"    wire f_in_transfer  = {in_tx};",
        f"    wire f_out_transfer = {out_tx};",
        f"    stream_tokens #(",
        f"        .IN_WEIGHT({spec['in_weight']}), .OUT_WEIGHT({spec['out_weight']}),",
        f"        .MIN_DIFF({spec['min_diff']}), .MAX_DIFF({spec['max_diff']}),",
        f"        .CHECK_SPURIOUS({1 if spec['spurious'] else 0})",
        f"    ) f_tokens (",
        f"        .clk(clk), .rst(rst),",
        f"        .in_transfer(f_in_transfer), .out_transfer(f_out_transfer),",
        f"        .source_valid({any_sv})",
        "    );",
    ]

    # Block-specific extras.
    if spec["extra"]:
        lines.append("")
        lines += ["    " + l for l in spec["extra"]]

    # Covers: traffic actually flows (guards the assumptions against vacuity).
    src0 = sources[0][0]
    lines += [
        "",
        "    // Covers: real traffic reaches the output (guards against over-constraining).",
        "    reg [7:0] f_out_count = 8'd0;",
        "    always @(posedge clk)",
        "        if (rst) f_out_count <= 8'd0;",
        "        else if (f_out_transfer && !(&f_out_count)) f_out_count <= f_out_count + 8'd1;",
        "    always @(*) cover (f_out_count == 8'd4);",
    ]
    if spec["cover_stall"]:
        lines.append(f"    always @(*) cover ({src0}_valid && !{src0}_ready);")
    lines += ["", "endmodule", ""]

    with open(path, "w") as f:
        f.write("\n".join(lines))
    return path

def emit(name, build_dir):
    """Emit ``<name>.v`` + ``<name>_formal.sv`` into ``build_dir``. Returns (paths..., spec)."""
    spec = REGISTRY[name]()
    dut  = spec["dut"]
    ios  = set()
    for _, ep in spec["sinks"] + spec["sources"]:
        ios |= {ep.valid, ep.ready, ep.first, ep.last} | {getattr(ep, f) for f, _ in _fields(ep)}
    for port, _, _ in spec["ties"]:
        ios.add(getattr(dut, port))
    for port in spec["consts"]:
        ios.add(getattr(dut, port))
    verilog = emit_verilog(dut, ios, name, build_dir)
    sv      = emit_formal_top(name, spec, os.path.join(build_dir, name + "_formal.sv"),
                              _port_dirs(verilog))
    return verilog, sv, spec
