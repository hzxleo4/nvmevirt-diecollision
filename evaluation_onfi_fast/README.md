# FAST '24 × ONFI, 16 GiB

This experiment isolates the ONFI multi-LUN page-register restriction described
in CLSSD from the page-to-die placement policy in Jun et al., FAST '24.
The workload definitions follow FAST '24; CLSSD's fio/BigTrace evaluation is
not the workload set for this repository.

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
3. Full filesystem/application experiments require the FAST host hint path
   through ext4, the block layer and NVMe. The runner must reject an unmodified
   host for that suite, rather than silently label an unhinted run as FAST-on.

Never run the upstream artifact's hard-coded real-device wipe scripts here.
All device writes must target a newly created and verified NVMeVirt namespace.

## Status

Implementation and validation are in progress. No performance numbers have
been obtained in this repository yet.
