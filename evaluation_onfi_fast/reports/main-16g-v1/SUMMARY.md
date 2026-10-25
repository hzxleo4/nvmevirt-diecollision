# FAST24 device-mechanism results

Explicit NVMe hints on the stock kernel; this is not an ext4/SQLite/Filebench end-to-end reproduction.

Source run: `evaluation_onfi_fast/results/main-16g-v1`. Source commit: `3b6d21b39e81e00ddcd58167aa702b7caa6f823a`.
16 GiB physical reservation; 4 channels × 2 dies; 32 KiB flash pages.
Each read sample is a complete 8 MiB pass (256 completed commands).
Samples within one layout reuse that layout; they are not independent reconstruction trials.
Mean latency uses fio lat; P99 uses clat. fio burst duration is quantized to milliseconds.
Averaged P99 values are not a pooled P99.

| Group | Case | MiB/s | Stddev | Mean µs | Mean P99 µs | ONFI waits |
|---|---|---:|---:|---:|---:|---:|
| A | append_random | 1731.75 | 339.00 | 501.46 | 1238.63 | 0 |
| A | append_worst | 398.73 | 4.83 | 2428.65 | 4530.72 | 0 |
| A | contiguous | 2040.32 | 432.99 | 393.92 | 939.76 | 0 |
| A | overwrite_random | 1643.60 | 343.30 | 527.93 | 1094.45 | 0 |
| A | overwrite_worst | 395.72 | 11.18 | 2417.30 | 4414.94 | 0 |
| B | append_random | 1745.08 | 313.42 | 492.83 | 1301.30 | 0 |
| B | append_worst | 397.46 | 6.59 | 2413.53 | 4576.60 | 0 |
| B | contiguous | 2164.44 | 438.29 | 380.45 | 749.29 | 0 |
| B | overwrite_random | 1692.49 | 319.50 | 510.25 | 1080.80 | 0 |
| B | overwrite_worst | 394.92 | 8.57 | 2430.59 | 4355.96 | 0 |
| C | append_random | 1867.62 | 469.55 | 439.69 | 1036.29 | 0 |
| C | append_worst | 2046.98 | 474.06 | 398.92 | 899.75 | 0 |
| C | contiguous | 1938.84 | 483.57 | 436.41 | 911.91 | 0 |
| C | overwrite_random | 1793.02 | 435.70 | 464.07 | 846.92 | 0 |
| C | overwrite_worst | 2171.43 | 364.51 | 368.01 | 679.80 | 0 |
| D | append_random | 2052.06 | 598.29 | 436.02 | 1008.98 | 0 |
| D | append_worst | 1865.08 | 597.92 | 483.41 | 1098.55 | 0 |
| D | contiguous | 2062.22 | 360.05 | 388.59 | 779.61 | 0 |
| D | overwrite_random | 2092.06 | 585.74 | 428.61 | 801.18 | 0 |
| D | overwrite_worst | 1958.10 | 300.56 | 393.16 | 773.60 | 0 |

| Case | Comparison | Throughput change |
|---|---|---:|
| append_random | ONFI cost B/A | +0.77% |
| append_random | FAST with ONFI C/B | +7.02% |
| append_random | FAST without ONFI D/A | +18.50% |
| append_random | ONFI with FAST C/D | -8.99% |
| append_worst | ONFI cost B/A | -0.32% |
| append_worst | FAST with ONFI C/B | +415.02% |
| append_worst | FAST without ONFI D/A | +367.75% |
| append_worst | ONFI with FAST C/D | +9.75% |
| contiguous | ONFI cost B/A | +6.08% |
| contiguous | FAST with ONFI C/B | -10.42% |
| contiguous | FAST without ONFI D/A | +1.07% |
| contiguous | ONFI with FAST C/D | -5.98% |
| overwrite_random | ONFI cost B/A | +2.97% |
| overwrite_random | FAST with ONFI C/B | +5.94% |
| overwrite_random | FAST without ONFI D/A | +27.29% |
| overwrite_random | ONFI with FAST C/D | -14.29% |
| overwrite_worst | ONFI cost B/A | -0.20% |
| overwrite_worst | FAST with ONFI C/B | +449.84% |
| overwrite_worst | FAST without ONFI D/A | +394.82% |
| overwrite_worst | ONFI with FAST C/D | +10.89% |

Read-phase programs: 0.
Read-phase ONFI waits: 0.
Construction counters and wall time are in construction.csv; they are separate from read performance.

No ONFI program-vs-read wait was exercised in the read phase. A/B and C/D throughput differences here must not be interpreted as an ONFI penalty; they include run-to-run measurement variation.
