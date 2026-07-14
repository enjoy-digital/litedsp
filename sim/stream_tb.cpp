// This file is part of LiteDSP.
// Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
// SPDX-License-Identifier: BSD-2-Clause
//
// Generic Verilator testbench for streaming blocks: any number of sinks (0..N), one source,
// with seeded-random backpressure on both sides. The per-block port map (TB_DUT, TB_N_SINKS,
// TB_N_IN/TB_N_OUT, tb_sink_fields[], tb_set_sink_valid/tb_get_sink_ready/tb_set_in/tb_get_out)
// is generated into tb_ports.h by sim/run_blocks.py from the block's stream layouts.
//
// Usage: V<top> <in_file> <n_out> <out_file> [--seed S] [--throttle T] [--ready-rate R]
//   in_file    : TB_N_IN integer columns per line (sink 0 fields first, then sink 1, ...).
//   --seed S   : PRNG seed for the sink/source timing randomization (default 1).
//   --throttle T   : probability (%) of holding back a sink's next sample each cycle (default 25).
//   --ready-rate R : probability (%) of asserting source_ready each cycle (default 75).
// Terminates after exactly n_out captured output samples (generous cycle timeout otherwise).

#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "tb_ports.h"
#include "verilated.h"

// Seeded xorshift32 PRNG: one stream per sink (valid throttling) plus one for source ready,
// so per-port timing patterns are independent and reproducible from --seed.
struct XorShift32 {
    uint32_t state;
    explicit XorShift32(uint32_t seed) : state(seed ? seed : 1) {}
    uint32_t next() {
        uint32_t x = state;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        return state = x;
    }
    bool percent(int p) { return (next() % 100) < (uint32_t)p; }
};

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);

    // Arguments: positional <in_file> <n_out> <out_file> + optional backpressure flags.
    const char* fin_path  = nullptr;
    const char* fout_path = nullptr;
    int      n_out      = 0;
    uint32_t seed       = 1;
    int      throttle   = 25;
    int      ready_rate = 75;
    int      pos        = 0;
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--seed")       && i + 1 < argc) { seed       = (uint32_t)strtoul(argv[++i], nullptr, 0); continue; }
        if (!strcmp(argv[i], "--throttle")   && i + 1 < argc) { throttle   = atoi(argv[++i]); continue; }
        if (!strcmp(argv[i], "--ready-rate") && i + 1 < argc) { ready_rate = atoi(argv[++i]); continue; }
        if      (pos == 0) fin_path  = argv[i];
        else if (pos == 1) n_out     = atoi(argv[i]);
        else if (pos == 2) fout_path = argv[i];
        pos++;
    }

    TB_DUT* dut = new TB_DUT;

    // Input columns (sink 0 fields first, then sink 1, ...); all sinks share the sample count.
    std::vector<std::vector<int32_t>> cols(TB_N_IN ? TB_N_IN : 1);
#if TB_N_IN
    FILE* fin = fopen(fin_path, "r");
    while (true) {
        int32_t v; bool ok = true;
        for (int k = 0; k < TB_N_IN; k++) {
            if (fscanf(fin, "%d", &v) != 1) { ok = false; break; }
            cols[k].push_back(v);
        }
        if (!ok) break;
    }
    fclose(fin);
#else
    (void)fin_path;
#endif
    size_t n_in = TB_N_IN ? cols[0].size() : 0;
    FILE*  fout = fopen(fout_path, "w");

    // Per-sink state: input index, presented-not-yet-accepted flag, global field offset, PRNG.
    enum { N_SINKS = TB_N_SINKS ? TB_N_SINKS : 1 };
    size_t in_i   [N_SINKS] = {};
    bool   pending[N_SINKS] = {};
    int    off    [N_SINKS] = {};
    std::vector<XorShift32> sink_prng;
    for (int s = 0; s < TB_N_SINKS; s++) {
        off[s] = (s == 0) ? 0 : off[s - 1] + tb_sink_fields[s - 1];
        sink_prng.push_back(XorShift32(seed + 0x9E3779B9u*(s + 1)));
    }
    XorShift32 ready_prng(seed + 0x7F4A7C15u);

    auto posedge = [&]() { dut->sys_clk = 1; dut->eval(); dut->sys_clk = 0; dut->eval(); };

    dut->sys_clk = 0; dut->sys_rst = 1; dut->eval();
    for (int i = 0; i < 4; i++) posedge();
    dut->sys_rst = 0;

    // Generous timeout: covers serial-MAC blocks (many cycles per sample) under throttling.
    int  out_n = 0;
    long guard = (long)(n_in + n_out)*256 + 20000;
    while (out_n < n_out && guard-- > 0) {
        // Sinks: present-or-hold. Once asserted, valid stays until the transfer completes
        // (stream protocol); throttling only delays the *next* presentation.
        for (int s = 0; s < TB_N_SINKS; s++) {
            if (!pending[s] && in_i[s] < n_in && !sink_prng[s].percent(throttle)) {
                for (int k = 0; k < tb_sink_fields[s]; k++)
                    tb_set_in(dut, off[s] + k, cols[off[s] + k][in_i[s]]);
                pending[s] = true;
            }
            tb_set_sink_valid(dut, s, pending[s]);
        }
        bool ready = ready_prng.percent(ready_rate);
        dut->source_ready = ready;
        dut->eval();                                   // Settle combinational at clk=0.
        bool consume[N_SINKS] = {};
        for (int s = 0; s < TB_N_SINKS; s++)
            consume[s] = pending[s] && tb_get_sink_ready(dut, s);
        if (dut->source_valid && ready && out_n < n_out) {
            for (int k = 0; k < TB_N_OUT; k++) fprintf(fout, "%d ", tb_get_out(dut, k));
            fprintf(fout, "\n");
            out_n++;
        }
        posedge();                                     // Perform the transfer / state update.
        for (int s = 0; s < TB_N_SINKS; s++)
            if (consume[s]) { in_i[s]++; pending[s] = false; }
    }
    fclose(fout);
    delete dut;
    return out_n == n_out ? 0 : 1;
}
