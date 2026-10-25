# FAST24 device-mechanism results

Explicit NVMe hints on the stock kernel; this is not an ext4/SQLite/Filebench end-to-end reproduction.

Source run: `evaluation_onfi_fast/results/main-16g-aio-v1`. Source commit: `e6aecf93a262c6fae6eb5da4a101f84f9b4970d2`.
16 GiB physical reservation; 4 channels × 2 dies; 32 KiB flash pages.
Each read sample is a complete 8 MiB pass (256 completed commands).
Samples within one layout reuse that layout; they are not independent reconstruction trials.
Timing uses CLOCK_MONOTONIC nanoseconds around a complete Linux AIO pass. Latency is userspace submission-to-reap.
Averaged P99 values are not a pooled P99.

| Group | Case | MiB/s | Stddev | Mean µs | Mean P99 µs | ONFI waits |
|---|---|---:|---:|---:|---:|---:|
| A | append_random | 2222.81 | 217.40 | 372.83 | 869.29 | 0 |
| A | append_worst | 408.76 | 10.69 | 2266.56 | 2961.02 | 0 |
| A | contiguous | 2770.00 | 208.04 | 298.91 | 460.21 | 0 |
| A | overwrite_random | 2022.56 | 259.59 | 403.57 | 1008.89 | 0 |
| A | overwrite_worst | 410.56 | 6.39 | 2270.96 | 2621.62 | 0 |
| B | append_random | 2128.62 | 179.69 | 382.31 | 868.86 | 0 |
| B | append_worst | 411.63 | 2.94 | 2257.13 | 2642.35 | 0 |
| B | contiguous | 2522.75 | 430.90 | 336.19 | 713.69 | 0 |
| B | overwrite_random | 2103.39 | 306.69 | 401.25 | 953.04 | 0 |
| B | overwrite_worst | 407.86 | 9.57 | 2277.33 | 3322.24 | 0 |
| C | append_random | 2590.97 | 443.11 | 330.71 | 645.71 | 0 |
| C | append_worst | 2690.75 | 395.60 | 319.67 | 639.35 | 0 |
| C | contiguous | 2720.39 | 295.48 | 311.13 | 530.66 | 0 |
| C | overwrite_random | 2588.27 | 485.14 | 340.31 | 753.86 | 0 |
| C | overwrite_worst | 2601.53 | 409.65 | 325.11 | 673.32 | 0 |
| D | append_random | 2639.89 | 372.77 | 321.25 | 632.00 | 0 |
| D | append_worst | 2683.35 | 274.46 | 312.75 | 524.17 | 0 |
| D | contiguous | 2728.46 | 420.95 | 322.08 | 597.34 | 0 |
| D | overwrite_random | 2704.72 | 223.88 | 300.07 | 455.02 | 0 |
| D | overwrite_worst | 2631.79 | 366.68 | 313.49 | 657.88 | 0 |

| Case | Comparison | Throughput change |
|---|---|---:|
| append_random | ONFI cost B/A | -4.24% |
| append_random | FAST with ONFI C/B | +21.72% |
| append_random | FAST without ONFI D/A | +18.76% |
| append_random | ONFI with FAST C/D | -1.85% |
| append_worst | ONFI cost B/A | +0.70% |
| append_worst | FAST with ONFI C/B | +553.67% |
| append_worst | FAST without ONFI D/A | +556.47% |
| append_worst | ONFI with FAST C/D | +0.28% |
| contiguous | ONFI cost B/A | -8.93% |
| contiguous | FAST with ONFI C/B | +7.83% |
| contiguous | FAST without ONFI D/A | -1.50% |
| contiguous | ONFI with FAST C/D | -0.30% |
| overwrite_random | ONFI cost B/A | +4.00% |
| overwrite_random | FAST with ONFI C/B | +23.05% |
| overwrite_random | FAST without ONFI D/A | +33.73% |
| overwrite_random | ONFI with FAST C/D | -4.31% |
| overwrite_worst | ONFI cost B/A | -0.66% |
| overwrite_worst | FAST with ONFI C/B | +537.85% |
| overwrite_worst | FAST without ONFI D/A | +541.03% |
| overwrite_worst | ONFI with FAST C/D | -1.15% |

Read-phase programs: 0.
Read-phase ONFI waits: 0.
Construction counters and wall time are in construction.csv; they are separate from read performance.

No ONFI program-vs-read wait was exercised in the read phase. A/B and C/D throughput differences here must not be interpreted as an ONFI penalty; they include run-to-run measurement variation.
