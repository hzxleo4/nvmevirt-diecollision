#!/usr/bin/env python3
"""Plot validated aggregate data; error bars show read-pass sample stdev."""
import argparse
import csv
import os
from pathlib import Path
os.environ.setdefault("MPLCONFIGDIR", "/tmp/nvmev-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("report", type=Path)
a = ap.parse_args()
rows = list(csv.DictReader((a.report / "aggregate.csv").open()))
lookup = {(r["group"], r["case"]): r for r in rows}
cases = [c for c in ("contiguous", "append_worst", "overwrite_worst", "append_random", "overwrite_random")
         if ("A", c) in lookup]
labels = {"A": "A: ONFI off, FAST off", "B": "B: ONFI on, FAST off",
          "C": "C: ONFI on, FAST on", "D": "D: ONFI off, FAST on"}
colors = {"A": "#79869b", "B": "#e18a37", "C": "#238c81", "D": "#4d71b8"}
fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
x = np.arange(len(cases))
for i, group in enumerate(labels):
    vals = [float(lookup[group, c]["MiB_s"]) for c in cases]
    err = [float(lookup[group, c]["stdev_MiB_s"]) for c in cases]
    ax.bar(x+(i-1.5)*.19, vals, .18, label=labels[group], color=colors[group],
           yerr=err, capsize=2, error_kw={"elinewidth": .8})
ax.set_xticks(x, [c.replace("_", "\n").title() for c in cases])
ax.set_ylabel("Read throughput (MiB/s)")
ax.set_title("FAST '24 device mechanism · 16 GiB · 8 MiB read passes")
ax.grid(axis="y", alpha=.2)
ax.set_axisbelow(True)
ax.legend(ncol=2, fontsize=9, loc="upper center", bbox_to_anchor=(.5, -.16), frameon=False)
for ext in ("png", "pdf", "svg"):
    fig.savefig(a.report / ("throughput."+ext), dpi=180)
plt.close(fig)
