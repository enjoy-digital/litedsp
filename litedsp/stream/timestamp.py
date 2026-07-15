#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Timestamped streams: a free-running time reference and edge taggers (see doc/timestamps.md).

LiteDSP does **not** thread time through the DSP blocks. A single :class:`LiteDSPTimeCore`
counts samples/cycles; :class:`LiteDSPTimestamper` tags the stream with that count at the
ingress edge (``timestamp``/``stream_id`` stream *params*, see
:func:`litedsp.common.time_param_layout`); everywhere else time is *computed*, not carried:
every block declares ``self.latency``, so ingress-time + sum(latency) gives the sample-accurate
time at any point of a chain. :class:`LiteDSPTimeUntagger` strips the params back to a plain
I/Q stream before entering time-agnostic blocks.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common import check, iq_layout, time_param_layout, TIMESTAMP_WIDTH

# Time Core ----------------------------------------------------------------------------------------

class LiteDSPTimeCore(LiteXModule):
    """Free-running ``width``-bit sample/cycle counter: the design's single time reference.

    ``count`` increments every cycle (= every sample at 1 sample/cycle) and is what the
    :class:`LiteDSPTimestamper`/packetizer edges latch. The counter is set by writing
    ``set_time`` (host disciplines it to an epoch); reads are atomic despite the multi-word
    CSR: write ``latch`` first, then read the frozen ``time``. A rising edge on the optional
    ``pps`` input latches ``count`` into ``pps_time`` (host measures the count-per-second to
    discipline/verify the sample clock); with ``with_irq=True`` each PPS edge raises an
    interrupt (``ev.pps``).

    Parameters
    ----------
    width : int
        Counter width in bits (64 by default: never wraps in practice).
    """
    def __init__(self, width=TIMESTAMP_WIDTH, with_csr=True, with_irq=False):
        check(width >= 2, "expected width >= 2")
        self.width     = width
        self.count     = Signal(width)  # Current time (increments every cycle).
        self.set_value = Signal(width)  # Time loaded on set_stb.
        self.set_stb   = Signal()       # 1-cycle strobe: load set_value into the counter.
        self.latch     = Signal()       # 1-cycle strobe: freeze count into latched.
        self.latched   = Signal(width)  # Frozen count (atomic multi-word read).
        self.pps       = Signal()       # PPS input (rising edge latches pps_time).
        self.pps_time  = Signal(width)  # count at the last PPS rising edge.

        # # #

        # Counter.
        # --------
        self.sync += [
            self.count.eq(self.count + 1),
            If(self.set_stb, self.count.eq(self.set_value)),
        ]

        # Read Latch.
        # -----------
        self.sync += If(self.latch, self.latched.eq(self.count))

        # PPS Latch.
        # ----------
        pps_d = Signal()
        self.sync += [
            pps_d.eq(self.pps),
            If(self.pps & ~pps_d, self.pps_time.eq(self.count)),
        ]

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev     = EventManager()
        self.ev.pps = EventSourceProcess(edge="rising", description="PPS edge (pps_time updated).")
        self.ev.finalize()
        self.comb += self.ev.pps.trigger.eq(self.pps)

    def add_csr(self):
        self._set_time = CSRStorage(self.width, name="set_time",
            description="Set the time counter (loaded on write of the last word).")
        self._latch    = CSRStorage(1, name="latch",
            description="Freeze count into time (write before reading: atomic multi-word read).")
        self._time     = CSRStatus(self.width, name="time",
            description="Frozen time (write latch first).")
        self._pps_time = CSRStatus(self.width, name="pps_time",
            description="count at the last PPS rising edge (stable between PPS pulses).")
        self.comb += [
            self.set_value.eq(self._set_time.storage),
            self.set_stb.eq(self._set_time.re),
            self.latch.eq(self._latch.re),
            self._time.status.eq(self.latched),
            self._pps_time.status.eq(self.pps_time),
        ]

# Timestamper --------------------------------------------------------------------------------------

class LiteDSPTimestamper(LiteXModule):
    """Tag the I/Q stream with its ingress time (``timestamp``/``stream_id`` params, latency 0).

    Passthrough on the payload; the source gains the :func:`litedsp.common.time_param_layout`
    params. ``time`` is sampled from the parent-connected :class:`LiteDSPTimeCore`: on a framed
    stream the tag is latched at each frame ``first`` and held for the whole frame (all samples
    of a frame carry the frame's ingress time — recover sample k's time as ``timestamp + k``);
    on an unframed stream (no ``first`` seen) every sample carries its own ingress time.
    Ingress time is the acceptance cycle (``valid & ready``).

    Parameters
    ----------
    width : int
        Timestamp width in bits (match the TimeCore).
    stream_id : int
        Reset value of the 8-bit stream identifier tagged onto every sample (CSR-settable).
    """
    def __init__(self, data_width=16, width=TIMESTAMP_WIDTH, stream_id=0, with_csr=True):
        check(width >= 2, "expected width >= 2")
        check(0 <= stream_id <= 255, "expected 0 <= stream_id <= 255")
        self.data_width = data_width
        self.width      = width
        self.latency    = 0
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(stream.EndpointDescription(
            payload_layout=iq_layout(data_width),
            param_layout=time_param_layout(width)))
        self.time      = Signal(width)                # Current time (connect LiteDSPTimeCore.count).
        self.stream_id = Signal(8, reset=stream_id)   # Stream identifier tag.

        # # #

        # Datapath.
        # ---------
        in_frame = Signal()       # Inside a first-delimited frame (past its first sample).
        stamp    = Signal(width)  # Time latched at the current frame's first sample.
        capture  = Signal()       # This beat carries a freshly sampled time.
        xfer     = Signal()       # A sample transfers this beat.
        self.comb += [
            self.source.valid.eq(self.sink.valid),
            self.sink.ready.eq(self.source.ready),
            self.source.i.eq(self.sink.i),
            self.source.q.eq(self.sink.q),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
            capture.eq(self.sink.first | ~in_frame),
            self.source.timestamp.eq(Mux(capture, self.time, stamp)),
            self.source.stream_id.eq(self.stream_id),
            xfer.eq(self.source.valid & self.source.ready),
        ]

        # Frame Tracking.
        # ---------------
        self.sync += If(xfer,
            in_frame.eq(~self.sink.last & (self.sink.first | in_frame)),
            If(capture, stamp.eq(self.time)),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._stream_id = CSRStorage(8, reset=self.stream_id.reset.value, name="stream_id",
            description="Stream identifier tagged onto every sample.")
        self.comb += self.stream_id.eq(self._stream_id.storage)

# Time Untagger ------------------------------------------------------------------------------------

class LiteDSPTimeUntagger(LiteXModule):
    """Strip the ``timestamp``/``stream_id`` params: tagged I/Q -> plain I/Q (latency 0).

    The boundary back into time-agnostic DSP blocks (inverse of :class:`LiteDSPTimestamper` on
    the layout; the payload and ``first``/``last`` framing pass through untouched).

    Parameters
    ----------
    width : int
        Timestamp width in bits of the tagged sink (match the tagging point).
    """
    def __init__(self, data_width=16, width=TIMESTAMP_WIDTH):
        check(width >= 2, "expected width >= 2")
        self.data_width = data_width
        self.latency    = 0
        self.sink   = stream.Endpoint(stream.EndpointDescription(
            payload_layout=iq_layout(data_width),
            param_layout=time_param_layout(width)))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        self.comb += self.sink.connect(self.source, omit={"timestamp", "stream_id"})
