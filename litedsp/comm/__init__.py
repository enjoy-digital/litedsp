#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Communication blocks: demodulators, carrier/timing recovery, frame sync, coding, mapping, OFDM CP."""

from litedsp.comm.am_demod        import LiteDSPAMDemod
from litedsp.comm.coding          import LiteDSPScrambler, LiteDSPDescrambler, LiteDSPCRC, LiteDSPConvEncoder
from litedsp.comm.correlator      import LiteDSPCorrelator
from litedsp.comm.diff            import LiteDSPDifferentialEncoder, LiteDSPDifferentialDecoder
from litedsp.comm.fm_demod        import LiteDSPFMDemod
from litedsp.comm.frame_sync      import LiteDSPFrameSync
from litedsp.comm.interleaver     import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver
from litedsp.comm.ldpc            import LiteDSPLDPCEncoder, LiteDSPLDPCDecoder
from litedsp.comm.ldpc_parallel   import LiteDSPLDPCDecoderZParallel
from litedsp.comm.mapper          import LiteDSPSymbolMapper
from litedsp.comm.ofdm            import LiteDSPCPInsert, LiteDSPCPRemove
from litedsp.comm.ofdm_eq         import LiteDSPOFDMEqualizer
from litedsp.comm.phase_detect    import LiteDSPPhaseDetect
from litedsp.comm.pll             import LiteDSPCarrierLoop, LiteDSPPLL, LiteDSPCostas, LiteDSPQPSKCostas
from litedsp.comm.puncture        import LiteDSPPuncturer, LiteDSPDepuncturer
from litedsp.comm.rs              import (
    LiteDSPRSEncoder, LiteDSPRSDecoder,
    LiteDSPCCSDSRSEncoder, LiteDSPCCSDSRSDecoder,
)
from litedsp.comm.slicer          import LiteDSPSlicer
from litedsp.comm.soft_demap      import LiteDSPSoftDemapper
from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
from litedsp.comm.viterbi         import LiteDSPViterbiDecoder
