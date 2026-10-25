#!/usr/bin/env python3
"""Summarize complete, validated SQLite/Filebench ONFI A/B experiments."""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import statistics as st
import tarfile

from summarize import delta, stats


def read(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def measured(folder, phase):
    d = delta(stats(folder / f"{phase}.after.stats"), stats(folder / f"{phase}.before.stats"))
    if d != read(folder / f"{phase}.counters.json") or any(v < 0 for v in d.values()):
        raise ValueError(f"invalid counter delta: {folder}/{phase}")
    return d


def host_counter(folder, phase, key):
    def value(suffix):
        line = next(x for x in (folder / f"{phase}.{suffix}.stats").read_text().splitlines()
                    if x.startswith("fast24 "))
        return int(dict(x.split("=") for x in line.split()[1:])[key])
    return value("after") - value("before")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("result", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    m = read(a.result / "manifest.json")
    if m["suite"] != "stock_host_applications_onfi_only" or m["status"] != "passed":
        raise ValueError("refusing incomplete or wrong-suite results")
    if m["fast_placement"] or read(a.result / "vm.original.json") != read(a.result / "vm.restored.json"):
        raise ValueError("unexpected FAST switch or unrestored VM settings")
    construction, reads, trials = [], [], []
    for item in m["plan"]:
        folder = a.result / f"r{item['repeat']}" / item["group"] / item["workload"]
        if not read(folder / "case.json")["validated"] or not read(folder / "verification.json")["verified"]:
            raise ValueError(f"unvalidated case: {folder}")
        line = next(x for x in (folder / "final.stats").read_text().splitlines() if x.startswith("fast24 "))
        flags = {k: int(v) for k, v in (x.split("=") for x in line.split()[1:])}
        if flags["onfi"] != int(item["group"] == "B") or any(flags[k] for k in
                ("placement", "rejected", "append_hints", "overwrite_hints")):
            raise ValueError(f"unexpected active feature switches or I/O errors: {folder}")
        base = {k: item[k] for k in ("workload", "group", "repeat")}
        sql = item["workload"] == "sqlite"
        dataset = read(folder / "dataset.json")
        build = read(folder / ("build.json" if sql else "append.json"))
        extents = re.search(r": (\d+) extents? found", (folder / "filefrag.log").read_text()) if sql else None
        record = base | {
            "construction_s": build["seconds"] if sql else build["wall_including_drain_seconds"],
            "process_wall_s": build["process_wall_seconds"],
            "wall_with_drain_s": build["wall_including_drain_seconds"],
            "append_loop_MiB_s": "" if sql else build["MiB_s"],
            "append_flowops": "" if sql else build["flowops"]["appendfile1"]["ops"],
            "append_reported_bytes": "" if sql else build["flowops"]["appendfile1"]["ops"] * (16384 if item["workload"] == "fileserver_small" else 32768),
            "dataset_bytes": dataset["database_bytes"] if sql else dataset["bytes"],
            "dummy_bytes": dataset.get("dummy_bytes", 0),
            "appended_file_bytes": dataset.get("appended_bytes", 0),
            "sqlite_extents": int(extents[1]) if extents else "",
            "host_write_commands": host_counter(folder, "build" if sql else "append", "writes"),
            **measured(folder, "build" if sql else "append")}
        construction.append(record)
        local = []
        for i in range(1, (m["sql_reads"] if sql else 1) + 1):
            phase = f"read{i}" if sql else "read"
            r = read(folder / f"{phase}.json")
            if sql:
                if r["records"] != m["records"] or r["seconds"] <= 0:
                    raise ValueError("incomplete SQLite select")
                throughput, latency, unit = r["records_s"], r["seconds"] * 1000, "records/s"
                duration = r["seconds"]
            else:
                if r["run_seconds"] != m["read_seconds"] or r["reads_s"] <= 0 or r["writes_s"] != 0:
                    raise ValueError("incomplete Filebench read")
                throughput, latency, unit = r["MiB_s"], r["flowops"]["readfile1"]["mean_ms"], "MiB/s"
                duration = r["run_seconds"]
            row = base | {"read": i, "throughput": throughput, "unit": unit,
                          "duration_s": duration, "latency_ms": latency,
                          "host_write_commands": host_counter(folder, phase, "writes"),
                          "host_read_4k_pages": host_counter(folder, phase, "read_pages"),
                          **measured(folder, phase)}
            if row["reads"] <= 0:
                raise ValueError("no NAND reads in measured read phase")
            row["nand_reads_per_MiB"] = row["reads"] * 256 / row["host_read_4k_pages"]
            local.append(row)
            reads.append(row)
        trials.append(base | {"construction_s": record["construction_s"],
                    "dataset_MiB": record["dataset_bytes"] / 1024**2,
                    "read_throughput": st.mean(r["throughput"] for r in local),
                    "read_unit": unit, "read_latency_ms": st.mean(r["latency_ms"] for r in local),
                    "nand_reads_per_MiB": sum(r["reads"] for r in local) * 256 / sum(r["host_read_4k_pages"] for r in local),
                    "build_onfi_events": record["onfi_events"], "build_onfi_ns": record["onfi_ns"],
                    "build_programs": record["programs"], "build_reads": record["reads"], "build_gc": record["gc"],
                    **{"read_" + k: sum(r[k] for r in local) for k in ("onfi_events", "onfi_ns", "programs", "reads", "gc")}})
    aggregates = []
    for w, g in sorted({(r["workload"], r["group"]) for r in trials}):
        selected = [r for r in trials if (r["workload"], r["group"]) == (w, g)]
        agg = {"workload": w, "group": g, "independent_trials": len(selected)}
        for key in ("construction_s", "dataset_MiB", "read_throughput", "read_latency_ms", "nand_reads_per_MiB"):
            values = [r[key] for r in selected]
            agg[key] = st.mean(values)
            agg[key + "_stdev"] = st.stdev(values) if len(values) > 1 else 0
        agg["read_unit"] = selected[0]["read_unit"]
        for key in ("build_onfi_events", "build_onfi_ns", "build_programs", "build_reads", "build_gc",
                    "read_onfi_events", "read_onfi_ns", "read_programs", "read_reads", "read_gc"):
            agg[key] = sum(r[key] for r in selected)
        aggregates.append(agg)
    comparisons = []
    lookup = {(r["workload"], r["group"]): r for r in aggregates}
    for w in sorted({r["workload"] for r in aggregates}):
        if (w, "A") not in lookup or (w, "B") not in lookup:
            continue
        off, on = lookup[w, "A"], lookup[w, "B"]
        comparisons.append({"workload": w,
            "build_time_change_percent": 100 * (on["construction_s"] / off["construction_s"] - 1),
            "read_throughput_change_percent": 100 * (on["read_throughput"] / off["read_throughput"] - 1),
            "read_latency_change_percent": 100 * (on["read_latency_ms"] / off["read_latency_ms"] - 1)})
    a.output.mkdir(parents=True, exist_ok=True)
    for name, rows in (("construction", construction), ("reads", reads), ("trials", trials),
                       ("aggregate", aggregates), ("comparisons", comparisons)):
        if rows:
            write_csv(a.output / (name + ".csv"), rows)
    (a.output / "source_manifest.json").write_text(json.dumps(m, indent=2) + "\n")
    report = ["# SQLite / Filebench：16 GiB ONFI 应用实验", "",
              f"原始结果：`{a.result}`；测试源码提交：`{m['git_head']}`。",
              f"状态：全部 {len(trials)} 个用例通过；正式实验：{'否（smoke）' if m['smoke'] else '是'}。",
              "A：ONFI 关；B：ONFI 开。两组 FAST placement 均关闭，主机内核未修改。",
              "协议和适配说明见 [APPLICATIONS.zh-CN.md](../../APPLICATIONS.zh-CN.md)。", "",
              f"SQLite：{m['records']:,} 条约 16 KiB 记录，逐条插入后追加并同步 100 KiB dummy；",
              f"每次构造后做 {m['sql_reads']} 次冷缓存 SELECT。Filebench：{m['files']:,} 个初始 128 KiB 文件，",
              f"10 线程，32/16 KiB 追加，累计 {m['append_mib']} MiB 后同步写回，direct I/O 读取 {m['read_seconds']} 秒。",
              "Filebench 采用固定追加量适配容量，**不是论文的不限量追加 60 秒**。", "",
              "## 按独立重建汇总", "",
              "均值 ± 样本标准差；SQLite 先对每次重建的冷读取均值，再对独立重建汇总。",
              "SQLite 的延迟是一次全表 SELECT 用时；Filebench 的延迟是一次 readwholefile 的平均用时，二者不可直接比较。",
              "Filebench 原始平均延迟精度为 0.1 ms；这套配置未采集应用 P99。",
              "Filebench 构造时间包括文件创建、追加、进程开销及末尾写回；SQLite 为辅助程序内部的完整构造时间。", "",
              "| 工作负载 | 组 | 独立重建 | 构造秒 | 读取吞吐 | 单位 | 读取延迟 ms |",
              "|---|---|---:|---:|---:|---|---:|"]
    for r in aggregates:
        report.append(f"| {r['workload']} | {r['group']} | {r['independent_trials']} | "
                      f"{r['construction_s']:.3f} ± {r['construction_s_stdev']:.3f} | "
                      f"{r['read_throughput']:.2f} ± {r['read_throughput_stdev']:.2f} | {r['read_unit']} | "
                      f"{r['read_latency_ms']:.3f} ± {r['read_latency_ms_stdev']:.3f} |")
    report += ["", "| 工作负载 | 构造用时变化 B/A | 读取吞吐变化 B/A | 读取延迟变化 B/A |", "|---|---:|---:|---:|"]
    for r in comparisons:
        report.append(f"| {r['workload']} | {r['build_time_change_percent']:+.2f}% | "
                      f"{r['read_throughput_change_percent']:+.2f}% | {r['read_latency_change_percent']:+.2f}% |")
    report += ["", "这些是观测到的均值差值，不是已经隔离出的 ONFI 因果效应；需结合计数器和逐轮布局差异判断。"]
    report += ["", "## ONFI / NAND 计数", "",
               "计数为各行全部重复的总和；累计等待不是应用墙钟损失，不能直接换算性能降幅。",
               "构造计数包含最终写回。只统计测量窗口，文件校验和 mkfs 不包含在内。", "",
               "| 工作负载 | 组 | 阶段 | ONFI 次数 | 累计等待 ms | NAND program | NAND read | GC 次数 |",
               "|---|---|---|---:|---:|---:|---:|---:|"]
    for r in aggregates:
        for prefix, label in (("build", "构造"), ("read", "读取")):
            report.append(f"| {r['workload']} | {r['group']} | {label} | {r[prefix+'_onfi_events']} | "
                          f"{r[prefix+'_onfi_ns']/1e6:.6f} | {r[prefix+'_programs']} | {r[prefix+'_reads']} | {r[prefix+'_gc']} |")
    if not sum(r["read_onfi_events"] for r in aggregates):
        report += ["", "**读取阶段 ONFI 等待均为零。读取吞吐的 A/B 差异不能归因为 ONFI 阻塞。**",
                   "这些工作负载按论文先构造再读；读阶段 NAND program 数和 GC 数见表。"]
    if not sum(r["build_onfi_events"] for r in aggregates):
        report += ["", "构造阶段也未观测到 ONFI 等待，构造用时差异同样不能作为 ONFI 罚时证据。"]
    zero_read = [r["workload"] for r in aggregates if r["group"] == "B" and not r["read_onfi_events"]]
    if zero_read:
        report += ["", "开启组读取 ONFI 等待为零的应用：" + "、".join(zero_read) + "。",
                   "这些应用的读取均值差异不能解释为 ONFI 直接阻塞；若开启组更快，也不能据此宣称 ONFI 会加速。",
                   "Filebench 并发构造可能产生不同布局，下表的每 MiB NAND read 次数用于核对这种差异。"]
    if sum(r["programs"] for r in reads) and not sum(r["host_write_commands"] + r["gc"] for r in reads):
        report += ["", "读取窗口虽无主机 WRITE、无 GC，仍有少量 NAND program。当前控制器报告 VWC=0，",
                   "syncfs 清理主机脏页并不保证触发显式 NVMe FLUSH；FTL 读到未满 32 KiB 页时会先补齐并 program。",
                   "这些计数保留在读阶段，没有移到构造阶段或过滤首遍读；详见每遍统计与 fast24_ftl.c 的 fast_read。"]
    report += ["", "## 全部独立重建结果", "",
               "NAND read/MiB = NAND read 次数 ÷ FTL 已映射的逻辑读页数 × 256（4 KiB 页）。",
               "它反映每 MiB 逻辑读需要多少次 NAND read，包含元数据访问；不是闪存传输字节的放大率。",
               "不同独立构造的布局可能不同，需结合这个指标解释读取吞吐差异。", "",
               "| 工作负载 | 组 | 轮次 | 构造 s | 数据 MiB | 读取吞吐 | 单位 | 读取延迟 ms | NAND read/MiB | 构造 ONFI | 读取 ONFI |",
               "|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|"]
    for r in trials:
        report.append(f"| {r['workload']} | {r['group']} | {r['repeat']} | {r['construction_s']:.3f} | "
                      f"{r['dataset_MiB']:.3f} | {r['read_throughput']:.2f} | {r['read_unit']} | "
                      f"{r['read_latency_ms']:.3f} | {r['nand_reads_per_MiB']:.2f} | {r['build_onfi_events']} | {r['read_onfi_events']} |")
    report += ["", "## 每一次读取", "",
               "| 工作负载 | 组 | 轮次 | 读序号 | 吞吐 | 单位 | 延迟 ms | ONFI 次数 | NAND program | NAND read |",
               "|---|---|---:|---:|---:|---|---:|---:|---:|---:|"]
    for r in reads:
        report.append(f"| {r['workload']} | {r['group']} | {r['repeat']} | {r['read']} | "
                      f"{r['throughput']:.2f} | {r['unit']} | {r['latency_ms']:.3f} | "
                      f"{r['onfi_events']} | {r['programs']} | {r['reads']} |")
    report += ["", "## 数据与验证", "",
               "- [全部构造数据](construction.csv)：含实际文件增长、报告追加字节数、计数器及写回时间。",
               "- [全部读取数据](reads.csv)、[独立重建](trials.csv)、[聚合](aggregate.csv)、[A/B 差值](comparisons.csv)。",
               "- [源码与运行配置](source_manifest.json)。",
               "- [原始日志和计数器归档](raw-results.tar.gz)，逐文件校验值见 [raw_inventory.csv](raw_inventory.csv)。",
               "- SQLite 所有字段、主键顺序和 integrity_check 通过；Filebench 读取前后大小及 SHA256 一致。",
               "- 应用无错误退出、无被拒绝的 NVMe I/O 或主机 FAST 提示；VM 参数已恢复。",
               "- 标准差反映独立构造的离散程度，不是显著性检验；Filebench 并发轨迹未逐请求锁定。"]
    ex = [r["sqlite_extents"] for r in construction if r["sqlite_extents"] != ""]
    if ex:
        report.append(f"- SQLite filefrag 记录为 {min(ex):,}–{max(ex):,} 个 extent；论文报告 DoF 5,005，不能声称文件布局完全一致。")
    if (a.output / "environment.json").is_file():
        report.append("- [本机硬件和已加载模块信息](environment.json)；CPU 频率未固定。")
    (a.output / "SUMMARY.md").write_text("\n".join(report) + "\n")
    # Compact audit inventory: all raw files except the compiled helper.
    inventory = []
    with (a.output / "raw-results.tar.gz").open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                for p in sorted(a.result.rglob("*")):
                    if p.is_file() and p.name != "sqlite_workload":
                        name = str(p.relative_to(a.result))
                        inventory.append({"path": name, "bytes": p.stat().st_size,
                                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
                        archive.add(p, arcname=name, recursive=False)
    write_csv(a.output / "raw_inventory.csv", inventory)
    print(a.output / "SUMMARY.md")


if __name__ == "__main__":
    main()
