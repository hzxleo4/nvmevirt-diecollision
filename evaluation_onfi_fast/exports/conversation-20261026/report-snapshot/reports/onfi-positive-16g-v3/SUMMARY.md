# ONFI positive control

This is a model diagnostic, NOT a FAST24 workload or an application result.
Source commit: `cc4b58e128cbcb21ac45105e90e4b8f9c0cce133`; raw run: `evaluation_onfi_fast/results/onfi-positive-16g-v3`.
16 GiB reservation, fixed 16,384 × 32 KiB commands, QD64, alternating reads and writes.
Reads lead writes by four flash pages, targeting the other LUN on the same channel.
The read and write regions do not overlap; all data is verified. Write hints are absent,
so placement cannot help this diagnostic. Throughput includes final buffer drain but not final verification.
Counters include final verification reads. Summed wait time is modeled scheduling delay,
not CPU time or an additive wall-clock delay; waits on different channels can overlap.

| Group | Trials | Total MiB/s | Stddev | ONFI waits | Summed wait ms |
|---|---:|---:|---:|---:|---:|
| A | 3 | 1484.60 | 50.76 | 0 | 0.000 |
| B | 3 | 834.32 | 1.74 | 24220 | 6284.090 |
| C | 3 | 836.42 | 1.56 | 24377 | 6325.870 |
| D | 3 | 1478.42 | 8.99 | 0 | 0.000 |

Diagnostic B/A throughput change: -43.80%.
This effect is specific to this artificial overlap pattern; do not generalize it to the paper's pure-read results.
