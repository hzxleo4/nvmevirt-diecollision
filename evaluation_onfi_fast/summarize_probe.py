#!/usr/bin/env python3
"""Summarize the ONFI positive control separately from FAST24 workloads."""
import argparse
import json
from pathlib import Path
import statistics
from summarize import stats, delta, write_csv

ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument("result", type=Path)
ap.add_argument("--output", type=Path, required=True)
a = ap.parse_args()
m = json.loads((a.result / "manifest.json").read_text())
if m["status"] != "passed" or m["suite"] != "onfi_positive_control":
    raise SystemExit("requires a complete, validated positive-control run")
rows = []
for item in m["plan"]:
    p = a.result / f"r{item['repeat']}" / item["group"] / item["case"]
    d = json.loads((p / "probe.json").read_text())
    if not json.loads((p / "case.json").read_text())["validated"] or not d["verified"] or d["completed"] != 16384:
        raise SystemExit("unvalidated/incomplete probe")
    diff = delta(stats(p / "probe.after.stats"), stats(p / "probe.before.stats"))
    if bool(diff["onfi_events"]) != bool(item["onfi"]):
        raise SystemExit("counter does not match ONFI switch")
    rows.append({"group": item["group"], "repeat": item["repeat"],
                 "MiB_s": d["total_MiB_s_including_flush"], "seconds": d["drained_ns"] / 1e9,
                 "mean_lat_us": d["mean_submission_to_reap_us"],
                 "p99_lat_us": d["p99_submission_to_reap_us"], **diff})
a.output.mkdir(parents=True, exist_ok=True)
write_csv(a.output / "probe.csv", rows)
report = ["# ONFI positive control", "",
          "This is a model diagnostic, NOT a FAST24 workload or an application result.",
          f"Source commit: `{m['git_head']}`; raw run: `{a.result}`.",
          "16 GiB reservation, fixed 16,384 × 32 KiB commands, QD64, alternating reads and writes.",
          "Reads lead writes by four flash pages, targeting the other LUN on the same channel.",
          "The read and write regions do not overlap; all data is verified. Write hints are absent,",
          "so placement cannot help this diagnostic. Throughput includes final buffer drain but not final verification.",
          "Counters include final verification reads. Summed wait time is modeled scheduling delay,",
          "not CPU time or an additive wall-clock delay; waits on different channels can overlap.", "",
          "| Group | Trials | Total MiB/s | Stddev | ONFI waits | Summed wait ms |",
          "|---|---:|---:|---:|---:|---:|"]
means = {}
for g in sorted({r["group"] for r in rows}):
    selected = [r for r in rows if r["group"] == g]
    values = [r["MiB_s"] for r in selected]
    means[g] = statistics.mean(values)
    sd = statistics.stdev(values) if len(values) > 1 else 0
    report.append(f"| {g} | {len(values)} | {means[g]:.2f} | {sd:.2f} | "
                  f"{sum(r['onfi_events'] for r in selected)} | {sum(r['onfi_ns'] for r in selected)/1e6:.3f} |")
if "A" in means and "B" in means:
    report += ["", f"Diagnostic B/A throughput change: {100*(means['B']/means['A']-1):+.2f}%.",
               "This effect is specific to this artificial overlap pattern; do not generalize it to the paper's pure-read results."]
(a.output / "SUMMARY.md").write_text("\n".join(report) + "\n")
(a.output / "source_manifest.json").write_text(json.dumps(m, indent=2))
print(a.output / "SUMMARY.md")
