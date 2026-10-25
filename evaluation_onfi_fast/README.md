# FAST '24 × ONFI, 16 GiB

[中文实现与测试结论](RESULTS.zh-CN.md)

This experiment isolates the ONFI multi-LUN page-register restriction described
in CLSSD from the page-to-die placement policy in Jun et al., FAST '24.
The paper-reproduction workload definitions follow FAST '24. The separate
[ordinary fio ONFI suite](FIO.zh-CN.md) checks uniform random mixed I/O;
it is not labeled as a FAST paper workload or the full CLSSD evaluation.

## Experiment contract

| Group | ONFI restriction | FAST placement |
|---|---:|---:|
| A | off | off |
| B | on | off |
| C | on | on |
| D | off | on |

Use the same FTL, geometry, channel model, GC policy, request stream and seed
across groups. Reload a fresh namespace and reconstruct its data for each case.
FAST placement changes future allocations; it does not rearrange existing data.
The 16 GiB physical reservation is `memmap=16G$8G`; logical capacity is smaller
because of over-provisioning. Report physical and logical bytes separately.

The FAST profile has four channels, two LUNs per channel, 32 KiB flash pages,
4 KiB mapping pages, approximately 36 us reads and 185 us programs. One channel
contains one two-LUN target in this explicit topology. The reference code uses
800 MiB/s for the channel model despite Table 2's `800 Mbps` label; record this
discrepancy rather than silently treating the two as equivalent.

Construction and read phases have separate timing and counter snapshots.
After a flush, a pure-read phase without GC programs should have zero ONFI
program-vs-read blocking. Same-die read queueing remains enabled in all groups.
An absent ONFI effect in such a phase is a valid result, not a failed experiment.

## Sources and provenance

* Paper: https://www.usenix.org/conference/fast24/presentation/jun
* Workload artifact: https://github.com/yuhun-Jun/fast24_ae/tree/89ba3a9
* Reference FTL: https://github.com/yuhun-Jun/nvmevirt_DA/tree/0c09dd7cf7c2ba79085fabca1127d55cf47c0599
* Reference host kernel: https://github.com/yuhun-Jun/kernel_5_15_DA/tree/39bc3f1e92e00487c4017787180cd815f2613d26
* ONFI: https://onfi.org/files/onfi_2_3a_gold.pdf (section 3.1.3);
  CLSSD cites revision 4.1 and explicitly assumes Program Page Register Clear
  Enhancement is disabled.

ONFI program setup waits for outstanding reads in the same target to finish
their NAND data output, not merely sensing. A read on another LUN may overlap
an already-started program, subject to command/data bus availability. This is
not a symmetric read/program exclusion throughout tPROG.

## Reproduction levels

1. Deterministic timing/placement tests exercise the actual C model.
2. Explicit NVMe write hints allow controlled append/overwrite mechanism
   experiments on the stock kernel. These are device-level experiments, not
   ext4 or SQLite/Filebench end-to-end reproductions.
3. Filesystem/application experiments with FAST placement require the FAST host hint path
   through ext4, the block layer and NVMe. The runner must reject an unmodified
   host for that suite, rather than silently label an unhinted run as FAST-on.
4. ONFI-only SQLite/Filebench A/B experiments run on the stock host with
   `fast_placement=0` in both groups. See [application protocol](APPLICATIONS.zh-CN.md).
   They use fresh ext4 namespaces, independent reconstructions and separate
   construction/read counters. Filebench uses a 4 GiB append budget to fit the
   16 GiB reservation; this differs from the paper's timed unlimited append.

Never run the upstream artifact's hard-coded real-device wipe scripts here.
All device writes must target a newly created and verified NVMeVirt namespace.

## Status

The implementation, four-group smoke test and 16 GiB mechanism matrix pass.
Per the user's scope preference, active changes stay in NVMeVirt and the test
programs; host-kernel adaptation is deferred. The stock host kernel is unchanged.
The tested result is a device-method reproduction with explicit hints, not a
claim that unmodified SQLite/Filebench supplies the paper's filesystem hints.

The [stock-host application report](reports/apps-onfi-16g-v1/SUMMARY.md) now adds
18 validated ONFI-only constructions, 60 cold SQLite SELECTs and twelve 60-second
Filebench reads. SQLite SELECT time is essentially unchanged (281.224 vs
281.215 ms). Both Filebench variants have zero read-phase ONFI waits; their
observed throughput differences include different layouts from concurrent
construction. Small construction waits are reported separately. All repetitions,
raw counters, logs and validation hashes are retained; this does not constitute
the FAST-hinted application experiment.

The [ordinary fio report](reports/fio-onfi-16g-v1/SUMMARY.md) adds 48 validated
fixed-volume A/B runs. At QD32, 4 KiB random workloads with 70%, 50%, and 30%
reads lose 11.61%, 22.21%, and 29.47% throughput with ONFI enabled; 32 KiB
50/50 loses 18.08%. Pure-read, pure-write and QD1 controls record no ONFI waits.
All cases use the same 2 GiB prefilled working set and 2 GiB measured I/O volume,
with no GC. This is a separate ONFI experiment, not a FAST paper workload.

The [four-group FAST fio report](reports/fio-fast-16g-v1/SUMMARY.md) adds 96
validated runs with the default-off raw-LBA overwrite adapter enabled in every
group. Only C/D apply the original-die policy. With ONFI enabled, FAST changes
4 KiB QD32 throughput by -0.96%, +0.29%, and +3.72%
for 70%, 50%, and 30% reads; 32 KiB 50/50 QD32 changes by -12.19%.
Fewer ONFI waits do not imply throughput recovery. All policy application
counts match overwritten mapping pages; all data checks pass with no GC.
This is a raw-fio overwrite adaptation, not the filesystem append/hint path.

The primary measured report is [main-16g-aio-v1](reports/main-16g-aio-v1/SUMMARY.md):
three independent constructions per group/layout, ten complete reads each,
600 measured passes. With ONFI enabled, FAST improves worst-case append and
overwrite throughput by 6.54x and 6.38x respectively. Both construction and
pure-read phases have zero ONFI program waits in these workloads. Consequently,
the observed A/B variation is **not** a measured ONFI penalty. The earlier
[fio report](reports/main-16g-v1/SUMMARY.md) uses millisecond timing and is retained
as a preliminary result, separately from the higher-resolution AIO report.

## Build and device mechanism experiments

```bash
./tests/run.sh
./evaluation_onfi_fast/00_check_environment.sh
PLAN_ONLY=1 ./evaluation_onfi_fast/run_all.sh
sudo ./evaluation_onfi_fast/run_all.sh --module-smoke --out evaluation_onfi_fast/results/module-smoke
sudo ./evaluation_onfi_fast/run_all.sh --timer aio --host-cpu 3 --repeats 3 --reads 10 --out evaluation_onfi_fast/results/main-16g
python3 evaluation_onfi_fast/summarize.py evaluation_onfi_fast/results/main-16g --output evaluation_onfi_fast/reports/main-16g
```

The profile is selected using `make NVMEV_PROFILE=fast24`; ordinary builds
retain the original default device selection. Both feature switches are module
parameters: `onfi_collision=0|1 fast_placement=0|1`. They do not require a
rebuild. Reloading creates a clean experiment boundary and avoids applying a
new hardware rule to already scheduled commands. Live switching is not exposed.

For prefilled raw-device fio, `fast_infer_overwrite=1` is a separate, default-off
adapter that recognizes overwrites of mapped LBAs inside NVMeVirt. Together
with `fast_placement=1`, it applies FAST's original-die overwrite rule without
host hints. Explicit hints retain precedence; unmapped LBAs use the ordinary
allocator. It does not infer file append or adjacency. See the
[four-group FAST fio protocol](FAST_FIO.zh-CN.md), including counters that
distinguish an enabled switch from actual policy applications.

The implementation uses one allocator and a 4 MiB write buffer for all groups.
Programs release buffer space at completion, and flush/read of a partial page
programs it with padding. Per-die GC preserves die affinity in every group.
These correctness choices differ from the reference artifact's asymmetric
buffer release and its incomplete per-die GC bookkeeping, so the code is a
method reproduction rather than a byte-for-byte copy of that artifact.

`nvme_hint.c` builds 256 × 32 KiB target pieces. Worst-case interference is
224 KiB; random interference is a seeded 32 KiB–32 MiB multiple of 32 KiB.
The paper's random range is 32 KiB–32 MiB (`--random-max-units 1024`, default),
whereas the published artifact uses 32 KiB–1 MiB (`--random-max-units 32`).
The manifest records this choice. Append layouts use scattered LBAs;
overwrite layouts retain contiguous LBAs.
The same hints are sent to every group and ignored when placement is off.
All target data is verified before measurement. Both timing paths use Linux
AIO, direct I/O and QD32, with complete 8 MiB passes. `--timer aio` measures the
complete pass with CLOCK_MONOTONIC nanoseconds and verifies every returned byte;
its latency is userspace submission-to-reap, including host processing.
`--timer fio` uses fio 3.28. This is explicitly a
device-mechanism analogue of the paper's hypothetical workloads; host syscall,
filesystem splitting and page-cache effects are absent. fio reports burst
runtime in milliseconds, so small throughput differences must not be interpreted
as precise causal effects without supporting counters and repetitions.

The iolog intentionally has no explicit `close`: fio 3.28 otherwise omits the
last QD-1 asynchronous completions. The runner requires exactly 8 MiB and 256
latency samples per pass. All raw runs stay under the ignored `results/`
directory; validated summaries and source manifests can be committed in
`reports/`. Repeated reads of one layout are distinguished from independent
reconstruction/seed trials.

## ONFI positive control (separate diagnostic)

```bash
sudo ./evaluation_onfi_fast/run_all.sh --collision-probe --repeats 3 --out evaluation_onfi_fast/results/onfi-positive-16g
python3 evaluation_onfi_fast/summarize_probe.py evaluation_onfi_fast/results/onfi-positive-16g --output evaluation_onfi_fast/reports/onfi-positive-16g
```

This is **not** a FAST24 workload. It checks that real NVMe I/O reaches the ONFI
timing path: 16,384 alternating 32 KiB reads/writes, QD64, disjoint 8 MiB read
and write regions. Reads lead writes by four flash pages to exercise the other
LUN on the same channel. Write hints are absent; FAST is not expected to improve
this diagnostic. The runner requires positive ONFI waits for B/C and zero for
A/D, verifies every read and final written data, drains writes, and unloads the
module. Reported throughput includes final drain. Summed modeled wait times
can overlap across channels and cannot be added to wall-clock runtime.
The [validated diagnostic report](reports/onfi-positive-16g-v3/SUMMARY.md) shows
positive waits only with ONFI enabled and a 43.80% B/A throughput reduction for
this specific overlap pattern. It must not be presented as the paper's ONFI cost.

## Paper workload coverage

| Paper evaluation | Current coverage | Scope difference |
|---|---|---|
| Hypothetical append/overwrite | Four groups, contiguous/worst/random layouts, completed | Explicit hints and raw device reads instead of ext4 and 1 MiB application read syscalls |
| SQLite: 10,000 records, approximately 16 KiB, 100 KiB interference | ONFI-only application A/B completed; FAST-hinted application pending | Stock host does not produce file hints |
| Filebench fileserver: 10,000 initial 128 KiB files, 10 threads, 32/16 KiB appends | ONFI-only application A/B completed; FAST-hinted application pending | Fixed 4 GiB append budget fits this host; stock host does not produce file hints; artifact uses 30 s versus the paper's 60 s append |

The device sees LBAs, not filenames. Without file hints, treating adjacent LBAs
as adjacent file blocks would change the method being tested. Full application
FAST-hinted numbers must therefore remain pending until a validated hint transport or an
explicitly labeled application-trace replay is available. No host-kernel
installation/reboot is part of the current test workflow.
