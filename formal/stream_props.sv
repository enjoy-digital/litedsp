//
// This file is part of LiteDSP.
//
// Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
// SPDX-License-Identifier: BSD-2-Clause
//
// Stream-protocol property checkers, bound to each block by the generated <name>_formal.sv top
// (see formal/wrapper.py). Written against the LiteX stream contract; yosys-friendly subset of
// SystemVerilog (immediate assertions + $past, no SVA sequences).

// Stream Stability ---------------------------------------------------------------------------------
//
// The LiteX stream contract on one endpoint: once valid is asserted with ready low, valid must
// stay asserted and the transfer contents (payload + first/last) must be unchanged on the next
// cycle. Instantiated with ASSUME=1 on DUT sinks (constrains the free anyseq environment to be a
// well-behaved producer) and ASSUME=0 on DUT sources (asserts the DUT behaves as one).

module stream_stability #(
    parameter WIDTH  = 1,
    parameter ASSUME = 0
) (
    input wire             clk,
    input wire             rst,
    input wire             valid,
    input wire             ready,
    input wire [WIDTH-1:0] payload
);
    reg f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;

    generate
        if (ASSUME) begin : g_assume
            always @(posedge clk)
                if (f_past_valid && !rst && !$past(rst) && $past(valid && !ready)) begin
                    assume (valid);                     // Producer may not retract valid...
                    assume (payload == $past(payload)); // ...nor change the payload while stalled.
                end
        end else begin : g_assert
            always @(posedge clk)
                if (f_past_valid && !rst && !$past(rst) && $past(valid && !ready)) begin
                    assert (valid);                     // DUT may not retract valid...
                    assert (payload == $past(payload)); // ...nor change the payload while stalled.
                end
        end
    endgenerate
endmodule

// Token Conservation -------------------------------------------------------------------------------
//
// Weighted transfer accounting: f_diff accumulates IN_WEIGHT per input transfer and -OUT_WEIGHT
// per output transfer (weights express the block's rate contract, e.g. iq_pack ratio=2 has
// IN_WEIGHT=1 / OUT_WEIGHT=2 so a balanced stream nets to zero). The invariant
// MIN_DIFF <= f_diff <= MAX_DIFF then means:
//   - no loss:        the difference is bounded by the block's declared latency + buffering
//                     (a lost token would let f_diff grow without bound);
//   - no duplication: the output count never runs ahead of what the consumed (or, for
//                     word-at-a-time unpackers, currently presented) input justifies.
// CHECK_SPURIOUS additionally asserts, for registered-output blocks, that source valid stays low
// until the first input transfer (no valid-from-nowhere after reset).

module stream_tokens #(
    parameter integer IN_WEIGHT      = 1,
    parameter integer OUT_WEIGHT     = 1,
    parameter integer MIN_DIFF       = 0,
    parameter integer MAX_DIFF       = 0,
    parameter         CHECK_SPURIOUS = 0
) (
    input wire clk,
    input wire rst,
    input wire in_transfer,
    input wire out_transfer,
    input wire source_valid
);
    // Running weighted difference (16-bit signed: far beyond any BMC depth used here).
    reg signed [15:0] f_diff = 0;
    always @(posedge clk)
        if (rst)
            f_diff <= 0;
        else
            f_diff <= f_diff + (in_transfer  ? IN_WEIGHT  : 0)
                             - (out_transfer ? OUT_WEIGHT : 0);

    always @(*)
        if (!rst) begin
            assert (f_diff >= MIN_DIFF); // No duplication.
            assert (f_diff <= MAX_DIFF); // No loss (bounded buffering).
        end

    // No valid-from-nowhere: source valid low until at least one input transfer.
    reg f_seen_in = 1'b0;
    always @(posedge clk)
        if (rst)
            f_seen_in <= 1'b0;
        else if (in_transfer)
            f_seen_in <= 1'b1;

    generate
        if (CHECK_SPURIOUS) begin : g_spurious
            always @(*)
                if (!rst && !f_seen_in)
                    assert (!source_valid);
        end
    endgenerate
endmodule
