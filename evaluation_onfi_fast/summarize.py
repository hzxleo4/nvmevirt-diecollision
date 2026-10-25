#!/usr/bin/env python3
"""Summarize validated FAST24 mechanism runs; incomplete runs are rejected."""
import argparse
import csv
import json
from pathlib import Path
import statistics


def stats(path):
    totals = {"onfi_events": 0, "onfi_ns": 0, "programs": 0, "reads": 0, "gc": 0}
    for line in path.read_text().splitlines():
        fields = dict(token.split("=", 1) for token in line.split()[1:] if "=" in token)
        if line.startswith("onfi "):
            totals["onfi_events"] += int(fields["wait_events"])
            totals["onfi_ns"] += int(fields["wait_ns"])
        if line.startswith("die "):
            for key, field in (("programs", "programs"), ("reads", "reads"), ("gc", "gc_count")):
                totals[key] += int(fields[field])
    return totals


def delta(after, before):
    return {k: after[k] - before[k] for k in after}


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    manifest = json.loads((a.result / "manifest.json").read_text())
    timer = manifest.get("timer", "fio")
    if manifest["status"] != "passed":
        raise SystemExit("Refusing incomplete/failed experiment")
    rows = []
    construction = []
    for item in manifest["plan"]:
        folder = a.result / f"r{item['repeat']}" / item["group"] / item["case"]
        meta = json.loads((folder / "case.json").read_text())
        if not meta["validated"]:
            raise SystemExit("Unvalidated case")
        prep = json.loads((folder / "construction.json").read_text())
        diff = delta(stats(folder / "read.iolog.constructed.stats"), stats(folder / "read.iolog.before.stats"))
        construction.append({"group": item["group"], "case": item["case"], "repeat": item["repeat"],
                             "seconds": prep["construction_seconds"], "dummy_bytes": prep["dummy_bytes"],
                             **diff})
        for i in range(1, item["reads"] + 1):
            data = json.loads((folder / f"read{i}.json").read_text())
            if timer == "aio":
                if data["io_bytes"] != 8388608 or data["completed"] != 256 or not data["verified"]:
                    raise SystemExit("Incomplete AIO pass")
                bandwidth = data["MiB_s"]
                mean_lat = data["mean_submission_to_reap_us"]
                p99 = data["p99_submission_to_reap_us"]
                duration_ms = data["elapsed_ns"] / 1e6
            else:
                if len(data["jobs"]) != 1:
                    raise SystemExit("expected one fio job")
                job = data["jobs"][0]
                read = job["read"]
                if job["error"] or read["io_bytes"] != 8388608 or read["clat_ns"]["N"] != 256:
                    raise SystemExit("Incomplete fio replay")
                bandwidth = read["bw_bytes"] / 1024**2
                mean_lat = read["lat_ns"]["mean"] / 1000
                p99 = read["clat_ns"]["percentile"]["99.000000"] / 1000
                duration_ms = read["runtime"]
            diff = delta(stats(folder / f"read{i}.after.stats"), stats(folder / f"read{i}.before.stats"))
            rows.append({"group": item["group"], "case": item["case"], "repeat": item["repeat"],
                         "read": i, "MiB_s": bandwidth, "mean_lat_us": mean_lat,
                         "p99_lat_us": p99, "runtime_ms": duration_ms, **diff})
    a.output.mkdir(parents=True, exist_ok=True)
    write_csv(a.output / "reads.csv", rows)
    write_csv(a.output / "construction.csv", construction)
    aggregates = []
    for group, case in sorted({(r["group"], r["case"]) for r in rows}):
        selected = [r for r in rows if (r["group"], r["case"]) == (group, case)]
        values = [r["MiB_s"] for r in selected]
        aggregates.append({"group": group, "case": case, "read_samples": len(values),
                           "layouts": len({r["repeat"] for r in selected}),
                           "MiB_s": statistics.mean(values),
                           "stdev_MiB_s": statistics.stdev(values) if len(values) > 1 else 0,
                           "mean_lat_us": statistics.mean(r["mean_lat_us"] for r in selected),
                           "mean_p99_lat_us": statistics.mean(r["p99_lat_us"] for r in selected),
                           "onfi_events": sum(r["onfi_events"] for r in selected),
                           "onfi_ns": sum(r["onfi_ns"] for r in selected),
                           "programs": sum(r["programs"] for r in selected)})
    lookup = {(r["group"], r["case"]): r for r in aggregates}
    for r in aggregates:
        base = lookup.get((r["group"], "contiguous"))
        r["normalized_to_contiguous"] = r["MiB_s"] / base["MiB_s"] if base else ""
    write_csv(a.output / "aggregate.csv", aggregates)
    comparisons = []
    for case in sorted({r["case"] for r in rows}):
        for label, base, treatment in (("ONFI cost B/A", "A", "B"), ("FAST with ONFI C/B", "B", "C"),
                                       ("FAST without ONFI D/A", "A", "D"), ("ONFI with FAST C/D", "D", "C")):
            if (base, case) in lookup and (treatment, case) in lookup:
                before = lookup[base, case]["MiB_s"]
                after = lookup[treatment, case]["MiB_s"]
                comparisons.append({"case": case, "comparison": label, "ratio": after / before,
                                    "throughput_change_percent": 100 * (after / before - 1)})
    if comparisons:
        write_csv(a.output / "comparisons.csv", comparisons)
    report = ["# FAST24 device-mechanism results", "",
              "Explicit NVMe hints on the stock kernel; this is not an ext4/SQLite/Filebench end-to-end reproduction.",
              "", f"Source run: `{a.result}`. Source commit: `{manifest['git_head']}`.",
              "16 GiB physical reservation; 4 channels × 2 dies; 32 KiB flash pages.",
              "Each read sample is a complete 8 MiB pass (256 completed commands).",
              "Samples within one layout reuse that layout; they are not independent reconstruction trials.",
              ("Timing uses CLOCK_MONOTONIC nanoseconds around a complete Linux AIO pass. Latency is userspace submission-to-reap."
               if timer == "aio" else "Mean latency uses fio lat; P99 uses clat. fio burst duration is quantized to milliseconds."),
              "Averaged P99 values are not a pooled P99.",
              "", "| Group | Case | MiB/s | Stddev | Mean µs | Mean P99 µs | ONFI waits |", "|---|---|---:|---:|---:|---:|---:|"]
    for r in aggregates:
        report.append(f"| {r['group']} | {r['case']} | {r['MiB_s']:.2f} | {r['stdev_MiB_s']:.2f} | "
                      f"{r['mean_lat_us']:.2f} | {r['mean_p99_lat_us']:.2f} | {r['onfi_events']} |")
    report += ["", "| Case | Comparison | Throughput change |", "|---|---|---:|"]
    for r in comparisons:
        report.append(f"| {r['case']} | {r['comparison']} | {r['throughput_change_percent']:+.2f}% |")
    report += ["", "Read-phase programs: " + str(sum(r["programs"] for r in rows)) + ".",
               "Read-phase ONFI waits: " + str(sum(r["onfi_events"] for r in rows)) + ".",
               "Construction counters and wall time are in construction.csv; they are separate from read performance."]
    if not sum(r["onfi_events"] for r in rows):
        report += ["", "No ONFI program-vs-read wait was exercised in the read phase. A/B and C/D throughput differences here must not be interpreted as an ONFI penalty; they include run-to-run measurement variation."]
    (a.output / "SUMMARY.md").write_text("\n".join(report) + "\n")
    (a.output / "source_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(a.output / "SUMMARY.md")


if __name__ == "__main__":
    main()
