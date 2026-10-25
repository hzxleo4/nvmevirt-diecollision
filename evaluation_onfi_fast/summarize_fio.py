#!/usr/bin/env python3
"""Report validated fixed-volume fio ONFI experiments and all raw samples."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics as st
import tarfile

from run_fio import checked_job
from summarize import delta, stats
from summarize_applications import write_csv


def read(path):
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    m = read(a.result / "manifest.json")
    if m["suite"] != "fio_random_onfi" or m["status"] != "passed":
        raise ValueError("refusing incomplete/wrong-suite run")
    rows = []
    preparation = []
    for item in m["plan"]:
        folder = a.result / f"r{item['repeat']}" / item["group"] / item["case"]
        if not read(folder / "case.json")["validated"]:
            raise ValueError("unvalidated case")
        j = checked_job(folder / "measure.json", m["io_bytes"])
        checked_job(folder / "prefill.json", m["working_bytes"])
        checked_job(folder / "verify.json", m["working_bytes"])
        fields = dict(x.split("=") for x in next(l for l in (folder / "final.stats").read_text().splitlines()
                                                if l.startswith("fast24 ")).split()[1:])
        if int(fields["onfi"]) != item["onfi"] or any(int(fields[k]) for k in
                ("placement", "rejected", "append_hints", "overwrite_hints")) or stats(folder / "final.stats")["gc"]:
            raise ValueError("invalid switches, errors or GC")
        c = delta(stats(folder / "measure.after.stats"), stats(folder / "measure.before.stats"))
        d = delta(stats(folder / "measure.drained.stats"), stats(folder / "measure.after.stats"))
        if c != read(folder / "measure.counters.json") or d != read(folder / "measure.drain_counters.json"):
            raise ValueError("counter delta mismatch")
        runtime = j["job_runtime"] / 1000
        row = item | {"runtime_s": runtime, "total_MiB_s": m["io_bytes"] / 1024**2 / runtime,
                      "kIOPS": sum(j[k]["total_ios"] for k in ("read", "write")) / runtime / 1000,
                      "read_bytes": j["read"]["io_bytes"], "write_bytes": j["write"]["io_bytes"],
                      "actual_read_percent": 100 * j["read"]["io_bytes"] / m["io_bytes"],
                      "iodepth_32_percent": j["iodepth_level"]["32"], **c,
                      **{"drain_" + k: v for k, v in d.items()}}
        for direction in ("read", "write"):
            v = j[direction]
            row[direction+"_mean_us"] = v["lat_ns"]["mean"] / 1000 if v["total_ios"] else ""
            row[direction+"_p99_clat_us"] = v["clat_ns"]["percentile"]["99.000000"] / 1000 if v["total_ios"] else ""
        rows.append(row)
        for phase in ("prefill", "verify"):
            preparation.append({k: item[k] for k in ("case", "group", "repeat")} | {"phase": phase,
                **read(folder / f"{phase}.timing.json"), **read(folder / f"{phase}.counters.json")})
    for r in rows:
        other = next(x for x in rows if x["case"] == r["case"] and x["repeat"] == r["repeat"] and x["group"] != r["group"])
        if (r["read_bytes"], r["write_bytes"]) != (other["read_bytes"], other["write_bytes"]):
            raise ValueError("A/B completed different read/write volumes")
    cases = list(dict.fromkeys(r["case"] for r in rows))
    aggregates = []
    for case in cases:
        for g in ("A", "B"):
            sub = [r for r in rows if r["case"] == case and r["group"] == g]
            agg = {"case": case, "group": g, "trials": len(sub)}
            for key in ("total_MiB_s", "kIOPS", "runtime_s", "read_mean_us", "read_p99_clat_us", "write_mean_us", "write_p99_clat_us"):
                values = [r[key] for r in sub if r[key] != ""]
                agg[key] = st.mean(values) if values else ""
                agg[key+"_stdev"] = st.stdev(values) if len(values) > 1 else 0 if values else ""
            for k in ("onfi_events", "onfi_ns", "programs", "reads", "gc", "drain_onfi_events", "drain_onfi_ns", "drain_programs"):
                agg[k] = sum(r[k] for r in sub)
            aggregates.append(agg)
    lookup = {(r["case"], r["group"]): r for r in aggregates}
    comparisons = [{"case": case, "throughput_change_percent": 100 *
                    (lookup[case,"B"]["total_MiB_s"] / lookup[case,"A"]["total_MiB_s"] - 1)} for case in cases]
    a.output.mkdir(parents=True, exist_ok=True)
    for name, data in (("trials", rows), ("aggregate", aggregates), ("comparisons", comparisons), ("preparation", preparation)):
        write_csv(a.output / (name + ".csv"), data)
    (a.output / "source_manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    def fmt(v):
        return "—" if v == "" else f"{v:.2f}"
    report = ["# fio：16 GiB ONFI 常规随机 I/O", "",
              f"状态：全部 {len(rows)} 个用例通过；{'冒烟，不能作为正式性能结果' if m['smoke'] else '正式测试'}。",
              f"源码基线：`{m['git_head']}`；工作区：{'有未提交改动，实际源文件 SHA256 见运行清单' if m['git_status'] else '干净'}。",
              f"fio：`{m['fio']}`；FAST placement 在两组均关闭。",
              f"16 GiB 物理预留，工作集 {m['working_bytes']/1024**2:g} MiB，每次测量完成 {m['io_bytes']/1024**2:g} MiB 总 I/O。",
              "均匀随机、libaio/direct I/O、单 job；R 表示读比例；A=ONFI 关，B=ONFI 开。",
              "先顺序预填充并显式 NVMe FLUSH，后测量、再 FLUSH、全范围模式校验。",
              "这不是 FAST 论文应用负载，也不是满盘 GC 稳态实验。协议见 [FIO.zh-CN.md](../../FIO.zh-CN.md)。", "",
              "## 吞吐与 ONFI", "",
              "均值 ± 独立重建间样本标准差。吞吐含读+写；等待次数/时间为全部重复的总和。",
              "等待可能重叠，累计等待不能直接换算为应用墙钟损失。计数窗口覆盖 fio 进程启动与结束，吞吐使用 fio 内部 job_runtime。", "",
              "| 配置 | A MiB/s | B MiB/s | B/A 变化 | A kIOPS | B kIOPS | B ONFI 次数 | B 累计等待 ms |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for change in comparisons:
        case = change["case"]; off, on = lookup[case,"A"], lookup[case,"B"]
        report.append(f"| {case} | {off['total_MiB_s']:.2f} ± {off['total_MiB_s_stdev']:.2f} | "
                      f"{on['total_MiB_s']:.2f} ± {on['total_MiB_s_stdev']:.2f} | {change['throughput_change_percent']:+.2f}% | "
                      f"{off['kIOPS']:.2f} | {on['kIOPS']:.2f} | {on['onfi_events']} | {on['onfi_ns']/1e6:.3f} |")
    report += ["", "## 读写延迟和设备操作", "",
               "平均延迟为 fio lat；P99 为 fio completion latency。三轮 P99 的均值不是合并请求的 P99。",
               "纯写窗口中若有额外 NAND read，会完整保留；其来源未逐请求定位，不能把整个进程窗口等同于 fio 内部计时窗口。",
               "非 FUA 写按进入设备写缓冲完成，写延迟不是 NAND program 完成延迟；读变慢也会改变写入到达节奏。", "",
               "| 配置 | 组 | 读平均 µs | 读 P99 µs | 写平均 µs | 写 P99 µs | NAND read | program | GC | 最后 flush 的 program / ONFI 次数 |",
               "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in aggregates:
        report.append(f"| {r['case']} | {r['group']} | {fmt(r['read_mean_us'])} | {fmt(r['read_p99_clat_us'])} | "
                      f"{fmt(r['write_mean_us'])} | {fmt(r['write_p99_clat_us'])} | {r['reads']} | {r['programs']} | {r['gc']} | "
                      f"{r['drain_programs']} / {r['drain_onfi_events']} |")
    report += ["", "## 全部逐轮结果", "",
               "| 配置 | 组 | 轮次 | 秒 | MiB/s | kIOPS | 实际读比例 | 读 P99 µs | 写 P99 µs | ONFI 次数 | 等待 ms |",
               "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        report.append(f"| {r['case']} | {r['group']} | {r['repeat']} | {r['runtime_s']:.3f} | {r['total_MiB_s']:.2f} | "
                      f"{r['kIOPS']:.2f} | {r['actual_read_percent']:.2f}% | {fmt(r['read_p99_clat_us'])} | "
                      f"{fmt(r['write_p99_clat_us'])} | {r['onfi_events']} | {r['onfi_ns']/1e6:.3f} |")
    report += ["", "## 验证与原始数据", "",
               "- 每个 A/B 配对的实际读写字节数相同；所有用例均无 GC、无拒绝 I/O、无 FAST 提示。",
               "- 全范围固定数据模式校验通过；该校验不能发现内容相同的 LBA 之间的别名。",
               "- [逐轮数据](trials.csv)、[聚合数据](aggregate.csv)、[变化](comparisons.csv)、[预填充/校验](preparation.csv)。",
               "- [运行清单](source_manifest.json)、[原始日志](raw-results.tar.gz)、[逐文件 SHA256](raw_inventory.csv)。"]
    (a.output / "SUMMARY.md").write_text("\n".join(report) + "\n")
    inventory = []
    with (a.output / "raw-results.tar.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with tarfile.open(fileobj=gz, mode="w") as tar:
                for p in sorted(a.result.rglob("*")):
                    if p.is_file():
                        name = str(p.relative_to(a.result))
                        inventory.append({"path": name, "bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
                        tar.add(p, arcname=name, recursive=False)
    write_csv(a.output / "raw_inventory.csv", inventory)
    print(a.output / "SUMMARY.md")


if __name__ == "__main__":
    main()
