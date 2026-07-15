#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""I/Q streams <-> framed wide-word streams: the generic glue toward host links.

``LiteDSPIQPacketizer`` frames the sample stream every ``samples_per_packet`` samples
(:class:`~litedsp.stream.framing.LiteDSPStreamFramer`) and packs samples into ``word_width``-bit words
(:class:`~litedsp.stream.adapt.LiteDSPIQPack`, first sample in the LSBs): the resulting
``data``+``last`` stream maps directly onto UDP payloads (LiteEth), host DMA word streams
(LitePCIe ``dma.sink``), or any AXI-Stream-with-tlast consumer. ``LiteDSPIQDepacketizer`` is the exact
inverse for the host -> FPGA direction.

With ``with_timestamp=True`` a 128-bit header (magic/version, ``stream_id``, sample count,
64-bit ``timestamp`` — see :data:`TIMESTAMP_HEADER_LAYOUT`) is prepended to every packet; the
field set is VITA-49-inspired but the format is explicitly **not** VITA-49 wire-compliant
(no class/trailer/fractional-time words — a lean LiteDSP-native header). Default off: the
word stream is bit-identical to the headerless format.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, iq_layout, time_param_layout, TIMESTAMP_WIDTH
from litedsp.stream.adapt   import LiteDSPIQPack, LiteDSPIQUnpack
from litedsp.stream.framing import LiteDSPStreamFramer, LiteDSPStreamDeframer

# Timestamp Header ---------------------------------------------------------------------------------
#
# 128-bit packet header, sent LSB-first in word_width chunks (like the sample packing).
# VITA-49-inspired field set; NOT wire-compliant with ANSI/VITA 49.x.
#
# bits [7:0]     magic     (TIMESTAMP_MAGIC)
# bits [15:8]    version   (TIMESTAMP_VERSION)
# bits [23:16]   stream_id
# bits [31:24]   reserved  (0)
# bits [63:32]   sample count of the packet
# bits [127:64]  timestamp of the packet's first sample (LiteDSPTimeCore count)

TIMESTAMP_MAGIC   = 0xDA
TIMESTAMP_VERSION = 0x01
TIMESTAMP_HEADER_BITS = 128

TIMESTAMP_HEADER_LAYOUT = [  # (field, offset, width) — documentation/host-parsing reference.
    ("magic",      0,  8),
    ("version",    8,  8),
    ("stream_id", 16,  8),
    ("reserved",  24,  8),
    ("count",     32, 32),
    ("timestamp", 64, 64),
]

# IQ Packetizer ------------------------------------------------------------------------------------

class LiteDSPIQPacketizer(LiteXModule):
    """I/Q stream -> ``word_width``-bit word stream with ``last`` every ``samples_per_packet``.

    Parameters
    ----------
    with_timestamp : bool
        Prepend the 128-bit timestamp header to every packet (see module docstring). Adds a
        ``time`` input Signal (connect :class:`~litedsp.stream.timestamp.LiteDSPTimeCore`
        ``count``): the time is latched at each packet's first sample. Off by default (word
        stream bit-identical to the headerless format).
    stream_id : int
        Reset value of the 8-bit stream identifier written into the header (CSR-settable).
    """
    def __init__(self, data_width=16, word_width=32, samples_per_packet=256, with_timestamp=False,
        stream_id=0, with_csr=True):
        ratio = word_width // (2*data_width)  # I/Q samples per word.
        check(ratio >= 1 and ratio*2*data_width == word_width, "expected ratio >= 1 and ratio*2*data_width == word_width")
        check(samples_per_packet % ratio == 0, "expected samples_per_packet % ratio == 0")
        check(0 <= stream_id <= 255, "expected 0 <= stream_id <= 255")
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([("data", word_width)])

        # # #

        self.framer = LiteDSPStreamFramer(length=samples_per_packet, data_width=data_width,
            with_csr=with_csr)
        self.pack   = LiteDSPIQPack(ratio=ratio, data_width=data_width)
        self.comb += self.sink.connect(self.framer.sink)

        if not with_timestamp:
            self.comb += [
                self.framer.source.connect(self.pack.sink),
                self.pack.source.connect(self.source),
            ]
            return

        # Timestamp Header Insertion.
        # ---------------------------
        check(TIMESTAMP_HEADER_BITS % word_width == 0, "expected word_width to divide the 128-bit timestamp header")
        n_hdr = TIMESTAMP_HEADER_BITS//word_width
        self.time      = Signal(TIMESTAMP_WIDTH)         # Current time (connect LiteDSPTimeCore.count).
        self.stream_id = Signal(8, reset=stream_id)      # Stream identifier written to the header.

        # Latch time/sample-count when each packet's first sample arrives at the packing stage
        # (valid & first, once per packet: the framer path is combinatorial, so the sample can
        # only *transfer* after the header it feeds has drained). Single register pair: the
        # packer (stream.Converter, one-word buffer) cannot accept the next packet's first
        # sample before the previous packet's words drained, and the header drains first.
        timestamp = Signal(TIMESTAMP_WIDTH)
        count     = Signal(32)
        armed     = Signal(reset=1)  # Waiting for the next packet's first sample.
        arrival   = Signal()         # First sample arriving this cycle (not latched yet).
        self.comb += [
            self.framer.source.connect(self.pack.sink),
            arrival.eq(armed & self.framer.source.valid & self.framer.source.first),
        ]
        self.sync += [
            If(arrival,
                timestamp.eq(self.time),
                count.eq(self.framer.length),
                armed.eq(0),
            ),
            If(self.framer.source.valid & self.framer.source.ready & self.framer.source.last,
                armed.eq(1),
            ),
        ]
        header = Signal(TIMESTAMP_HEADER_BITS)
        self.comb += header.eq(Cat(
            Constant(TIMESTAMP_MAGIC,   8),
            Constant(TIMESTAMP_VERSION, 8),
            self.stream_id,
            Constant(0, 8),
            Mux(arrival, self.framer.length, count),  # Live on the arrival cycle, then latched.
            Mux(arrival, self.time,          timestamp),
        ))

        # Header words first (while the packet's first payload word waits), then the payload.
        idx = Signal(max=max(n_hdr, 2))
        self.fsm = fsm = FSM(reset_state="HEADER")
        fsm.act("HEADER",
            If(self.pack.source.valid,               # First payload word ready: header is stable.
                self.source.valid.eq(1),
                self.source.first.eq(idx == 0),
                Case(idx, {k: self.source.data.eq(header[k*word_width:(k + 1)*word_width])
                           for k in range(n_hdr)}),
                If(self.source.ready,
                    NextValue(idx, idx + 1),
                    If(idx == (n_hdr - 1),
                        NextValue(idx, 0),
                        NextState("PAYLOAD"),
                    ),
                ),
            ),
        )
        fsm.act("PAYLOAD",
            self.pack.source.connect(self.source, omit={"first"}),
            If(self.source.valid & self.source.ready & self.source.last,
                NextState("HEADER"),
            ),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_timestamp_csr()

    def add_timestamp_csr(self):
        self._stream_id = CSRStorage(8, reset=self.stream_id.reset.value, name="stream_id",
            description="Stream identifier written into the packet timestamp header.")
        self.comb += self.stream_id.eq(self._stream_id.storage)

# IQ Depacketizer ----------------------------------------------------------------------------------

class LiteDSPIQDepacketizer(LiteXModule):
    """``word_width``-bit word stream -> I/Q stream (inverse of :class:`LiteDSPIQPacketizer`).

    Parameters
    ----------
    with_timestamp : bool
        Consume the 128-bit timestamp header at the start of every packet (see module
        docstring) and tag the I/Q source with the recovered ``timestamp``/``stream_id``
        params (:func:`litedsp.common.time_param_layout`; all samples of a packet carry the
        header values — strip with :class:`~litedsp.stream.timestamp.LiteDSPTimeUntagger`).
        Off by default (bit-identical headerless format).
    """
    def __init__(self, data_width=16, word_width=32, with_timestamp=False, with_csr=True):
        ratio = word_width // (2*data_width)  # I/Q samples per word.
        check(ratio >= 1 and ratio*2*data_width == word_width, "expected ratio >= 1 and ratio*2*data_width == word_width")
        self.sink = stream.Endpoint([("data", word_width)])
        if with_timestamp:
            self.source = stream.Endpoint(stream.EndpointDescription(
                payload_layout=iq_layout(data_width),
                param_layout=time_param_layout(TIMESTAMP_WIDTH)))
        else:
            self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.unpack   = LiteDSPIQUnpack(ratio=ratio, data_width=data_width)
        self.deframer = LiteDSPStreamDeframer(data_width=data_width, with_csr=with_csr)
        self.comb += self.unpack.source.connect(self.deframer.sink)

        if not with_timestamp:
            self.comb += [
                self.sink.connect(self.unpack.sink),
                self.deframer.source.connect(self.source),
            ]
            return

        # Timestamp Header Extraction.
        # ----------------------------
        check(TIMESTAMP_HEADER_BITS % word_width == 0, "expected word_width to divide the 128-bit timestamp header")
        n_hdr = TIMESTAMP_HEADER_BITS//word_width

        # Header of the packet about to emerge (pend) vs the packet currently draining (cur):
        # pend commits to cur on the packet's first output sample, so the pipeline tail of the
        # previous packet (unpack/deframer) keeps its own tags.
        header  = Signal(TIMESTAMP_HEADER_BITS)
        pending = Signal()  # Parsed header not committed yet (blocks the next parse).
        cur_ts  = Signal(TIMESTAMP_WIDTH)
        cur_id  = Signal(8)
        pend_ts = header[64:128]
        pend_id = header[16:24]

        idx = Signal(max=max(n_hdr, 2))
        self.fsm = fsm = FSM(reset_state="HEADER")
        fsm.act("HEADER",
            If(~pending,
                self.sink.ready.eq(1),
                If(self.sink.valid,
                    Case(idx, {k: NextValue(header[k*word_width:(k + 1)*word_width], self.sink.data)
                               for k in range(n_hdr)}),
                    NextValue(idx, idx + 1),
                    If(idx == (n_hdr - 1),
                        NextValue(idx, 0),
                        NextValue(pending, 1),
                        NextState("PAYLOAD"),
                    ),
                ),
            ),
        )
        fsm.act("PAYLOAD",
            self.sink.connect(self.unpack.sink),
            If(self.sink.valid & self.sink.ready & self.sink.last,
                NextState("HEADER"),
            ),
        )

        # Output tagging (deframer re-derives first from the incoming last).
        xfer = Signal()
        self.comb += [
            self.deframer.source.connect(self.source),
            self.source.timestamp.eq(Mux(self.source.first, pend_ts, cur_ts)),
            self.source.stream_id.eq(Mux(self.source.first, pend_id, cur_id)),
            xfer.eq(self.source.valid & self.source.ready),
        ]
        self.sync += If(xfer & self.source.first,
            cur_ts.eq(pend_ts),
            cur_id.eq(pend_id),
            pending.eq(0),
        )
