# Resource usage per block

Reference numbers from the FPGA implementation sweeps (`impl/run.py`, default block
parameters, 16-bit datapaths). Regenerate with `python3 impl/report.py` after a sweep
updates `impl/budgets.json`; CI checks new results against these budgets.

| module | ECP5 (Yosys/nextpnr) LUT/FF/BRAM/DSP | Artix-7 (Vivado) LUT/FF/BRAM/DSP | Fmax min (MHz) |
|---|---|---|---|
| `agc` | 377/57/0/8 | 179/57/0/4 | 54 |
| `channelizer` | 2786/1086/6/24 | 1280/310/2/24 | 78 |
| `cic_decimator` | 566/484/0/0 | 776/484/0/0 | 83 |
| `cic_interpolator` | 580/438/0/0 | 676/438/0/0 | 51 |
| `cic_parallel_x4` | 1393/482/0/0 | - | 48 |
| `combine` | 371/33/0/0 | 134/33/0/0 | 562 |
| `cordic_rot` | 1943/907/0/2 | 970/858/0/2 | 158 |
| `cordic_vec` | 1839/849/0/1 | 742/827/0/1 | 186 |
| `correlator` | 927/710/0/14 | 68/198/0/14 | 110 |
| `csr_sink` | 64/64/0/0 | - | 288 |
| `csr_source` | 1/33/0/0 | - | - |
| `dc_blocker` | 224/97/0/0 | 90/97/0/0 | 210 |
| `ddc` | 890/317/2/6 | 480/122/1/6 | 107 |
| `ddc_parallel_x4` | 1942/1071/8/18 | - | 42 |
| `duc` | 643/302/2/7 | 386/100/1/6 | 63 |
| `error_counter` | 97/64/0/0 | - | 369 |
| `farrow` | 652/281/0/14 | 470/207/0/6 | 55 |
| `fft` | 2987/360/0/28 | 1525/367/0/35 | 73 |
| `fft_iter` | 938/91/2/4 | 236/29/1/5 | 60 |
| `fir` | 2715/1555/0/32 | - | - |
| `fir_complex` | 181/106/0/2 | 105/38/0/8 | 118 |
| `fir_decimator` | 471/104/0/2 | 239/78/0/2 | 122 |
| `fir_interpolator` | 338/86/0/2 | 195/60/0/2 | 102 |
| `fir_parallel_x2` | 5221/2611/0/64 | - | - |
| `fir_parallel_x4` | 10351/4723/0/128 | - | - |
| `fm_demod` | 1720/790/0/4 | 264/398/0/5 | 111 |
| `framer` | 102/16/0/0 | - | 268 |
| `gain` | 59/33/0/2 | 21/33/0/8 | 376 |
| `goertzel` | 1374/336/0/17 | 709/143/0/12 | 52 |
| `halfband` | 394/94/0/2 | 213/68/0/2 | 94 |
| `histogram` | 389/22/0/0 | 110/22/0/0 | 102 |
| `iir_biquad` | 1614/834/0/24 | 218/35/0/36 | 84 |
| `iq_pack` | 21/133/0/0 | - | 153 |
| `iq_unpack` | 134/2/0/0 | - | 878 |
| `lms_equalizer` | 1741/522/0/56 | 643/389/0/60 | 59 |
| `magnitude` | 157/18/0/0 | 103/18/0/0 | 739 |
| `magnitude_cordic` | 1618/601/0/1 | 540/580/0/1 | 167 |
| `mixer` | 351/296/0/4 | 109/130/0/4 | 226 |
| `mixer_parallel_x2` | 511/334/0/8 | - | 272 |
| `mixer_parallel_x4` | 980/666/0/16 | - | - |
| `moving_average` | 246/87/0/0 | 172/85/0/0 | 157 |
| `nco` | 43/43/2/0 | 65/33/1/0 | 265 |
| `nco_parallel_x2` | 85/52/4/0 | - | 234 |
| `nco_parallel_x4` | 222/71/8/2 | - | 168 |
| `nco_qw` | 674/52/0/0 | 222/52/0/0 | 216 |
| `null_sink` | 65/32/0/0 | - | 305 |
| `pattern_source` | 114/65/0/0 | - | 353 |
| `power` | 969/106/0/2 | 189/106/0/2 | 143 |
| `psd` | 855/31/0/2 | 343/30/0/2 | 89 |
| `rms` | 1293/156/0/2 | 262/155/0/2 | 129 |
| `saturate` | 67/33/0/0 | 55/33/0/0 | 572 |
| `stats` | 289/186/0/2 | 92/114/0/3 | 113 |
| `stream_fifo` | 32/14/0/0 | - | 232 |
| `timing_recovery` | 1030/292/0/16 | 629/244/0/8 | 61 |
| `window` | 341/15/0/2 | 67/19/0/2 | 100 |
