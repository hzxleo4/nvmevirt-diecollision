#!/usr/bin/env python3
"""16 GiB, four-way FAST24 device-mechanism experiment.

This runner never chooses an existing physical disk. Each case creates its
own NVMeVirt device and refuses an already loaded module or mounted namespace.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
GROUPS = {"A": (0, 0), "B": (1, 0), "C": (1, 1), "D": (0, 1)}
CASES = ("contiguous", "append_worst", "append_random", "overwrite_worst", "overwrite_random")


def run(args, output=None, timeout=180):
    if output:
        with open(output, "w") as f:
            return subprocess.run(list(map(str, args)), cwd=ROOT, stdout=f,
                                  stderr=subprocess.STDOUT, check=True, timeout=timeout)
    return subprocess.run(list(map(str, args)), cwd=ROOT, check=True, timeout=timeout)


def capture(args):
    return subprocess.check_output(args, cwd=ROOT, text=True).strip()


def namespaces():
    return {Path(p).name for p in glob.glob("/sys/class/block/nvme*n*")
            if not (Path(p) / "partition").exists()}


def verify_device(name):
    sysdev = Path("/sys/class/block") / name
    model = (sysdev / "device/model").read_text().strip()
    if model != "NVMeVirt_FAST24":
        raise RuntimeError(f"refusing model {model!r}")
    if list(sysdev.glob(name + "p*")):
        raise RuntimeError("unexpected partitions on the fresh namespace")
    # lsblk includes descendants, so a mounted partition is also rejected.
    lsblk = json.loads(capture(["lsblk", "-J", "-o", "NAME,MOUNTPOINTS", "/dev/" + name]))
    def unmounted(node):
        return not any(node.get("mountpoints", [])) and all(unmounted(n) for n in node.get("children", []))
    if not all(unmounted(n) for n in lsblk["blockdevices"]):
        raise RuntimeError("namespace is mounted")
    if any((sysdev / "holders").iterdir()):
        raise RuntimeError("namespace has holders")
    return "/dev/" + name


def counters(path):
    path.write_text(Path("/proc/nvmev/debug").read_text())


def check_fio(path):
    data = json.loads(path.read_text())
    if not data.get("jobs") or any(j.get("error", 1) for j in data["jobs"]):
        raise RuntimeError(f"fio failed: {path}")
    if sum(j["read"]["io_bytes"] for j in data["jobs"]) != 8 * 1024 * 1024:
        raise RuntimeError(f"unexpected replay length: {path}")
    if sum(j["read"]["clat_ns"]["N"] for j in data["jobs"]) != 256:
        raise RuntimeError(f"missing replay completions: {path}")


def validate_log(path):
    errors = re.compile(r"BUG:|Oops:|KASAN:|kernel BUG|soft lockup|hung task|"
                        r"No free entry|Need to increase array|Invalid valid_len", re.I)
    if errors.search(path.read_text()):
        raise RuntimeError(f"kernel/model error; see {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--module-smoke", action="store_true")
    ap.add_argument("--collision-probe", action="store_true",
                    help="separate ONFI positive control; not a paper workload")
    ap.add_argument("--groups", nargs="+", choices=GROUPS, default=list(GROUPS))
    ap.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--reads", type=int, default=10)
    ap.add_argument("--iodepth", type=int, default=32)
    ap.add_argument("--seed", type=int, default=20261025)
    ap.add_argument("--cpus", default="7,8,9,10")
    ap.add_argument("--host-cpu", type=int, default=3)
    ap.add_argument("--timer", choices=("fio", "aio"), default="fio")
    ap.add_argument("--random-max-units", type=int, choices=(32, 1024), default=1024,
                    help="32 reproduces artifact range; 1024 reproduces paper text")
    ap.add_argument("--out", type=Path, default=ROOT / "evaluation_onfi_fast/results" /
                    datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    a = ap.parse_args()
    if min(a.repeats, a.reads, a.iodepth, a.seed) < 1:
        ap.error("repeat/read/queue/seed values must be positive")
    if a.collision_probe:
        if a.module_smoke:
            ap.error("choose module smoke or collision probe")
        a.cases = ["contiguous"]
    suite = "onfi_positive_control" if a.collision_probe else "device_mechanism"
    plan = [{"group": g, "onfi": GROUPS[g][0], "placement": GROUPS[g][1],
             "case": case, "repeat": rep, "seed": a.seed + rep,
             "reads": 0 if a.collision_probe else a.reads}
            for rep in range(1, a.repeats + 1)
            for g in a.groups[(rep - 1) % len(a.groups):] + a.groups[:(rep - 1) % len(a.groups)]
            for case in a.cases]
    if a.plan_only:
        print(json.dumps({"suite": suite, "mem_start": "8G", "mem_size": "16G",
                          "cpus": a.cpus, "host_cpu": a.host_cpu, "timer": a.timer,
                          "random_max_units": a.random_max_units,
                          "iodepth": a.iodepth, "plan": plan}, indent=2))
        return
    cmdline = Path("/proc/cmdline").read_text().strip()
    if "memmap=16G$8G" not in cmdline.split():
        raise RuntimeError("requires the verified boot reservation memmap=16G$8G")
    cpu_ids = [int(c) for c in a.cpus.split(",")]
    if len(cpu_ids) < 2 or len(set(cpu_ids)) != len(cpu_ids):
        raise RuntimeError("need distinct dispatcher and completion CPUs")
    if a.host_cpu in cpu_ids:
        raise RuntimeError("host CPU must be distinct from emulator CPUs")
    for cpu in cpu_ids + [a.host_cpu]:
        online = Path(f"/sys/devices/system/cpu/cpu{cpu}/online")
        if not online.parent.exists() or (online.exists() and online.read_text().strip() != "1"):
            raise RuntimeError(f"CPU {cpu} is offline")
    for tool in ("make", "cc", "fio", "insmod", "rmmod", "lsblk", "taskset"):
        if not shutil.which(tool):
            raise RuntimeError(f"missing tool {tool}")
    if a.check_only:
        print(json.dumps({"kernel": capture(["uname", "-r"]), "cmdline": cmdline,
                          "cpus": cpu_ids, "fio": capture(["fio", "--version"]),
                          "module_loaded": Path("/sys/module/nvmev").exists()}, indent=2))
        return
    if os.geteuid() != 0:
        raise RuntimeError("run with sudo; --plan-only and --check-only do not need root")
    if Path("/sys/module/nvmev").exists():
        raise RuntimeError("nvmev is already loaded; refusing to take over another run")
    a.out = a.out.resolve()
    a.out.mkdir(parents=True, exist_ok=False)
    manifest = {"suite": suite, "host_hint_path": "explicit_nvme_ioctl",
                "kernel": capture(["uname", "-r"]), "git_head": capture(["git", "rev-parse", "HEAD"]),
                "git_status": capture(["git", "status", "--porcelain"]), "cmdline": cmdline,
                "cpus": a.cpus, "host_cpu": a.host_cpu, "timer": a.timer,
                "random_max_units": a.random_max_units, "physical_bytes": 16 * 1024**3,
                "onfi_topology": "one target per channel, two LUNs per target",
                "channel_MiB_per_second": 800, "iodepth": a.iodepth, "plan": plan,
                "status": "running"}
    source_files = ("ssd.c", "ssd.h", "ssd_config.h", "channel_model.c", "onfi_model.h",
                    "fast24_ftl.c", "fast24_placement.h", "Kbuild", "io.c", "admin.c",
                    "evaluation_onfi_fast/runner.py", "evaluation_onfi_fast/nvme_hint.c",
                    "evaluation_onfi_fast/read_pass.c", "evaluation_onfi_fast/collision_probe.c")
    manifest["source_sha256"] = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                 for p in source_files}
    if a.collision_probe:
        manifest["diagnostic"] = {"iodepth": 64, "commands": 16384, "read_percent": 50,
                                  "request_bytes": 32768, "write_hints": "none",
                                  "not_a_paper_workload": True}
    (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    shutil.copy(ROOT / "ssd_config.h", a.out / "ssd_config.h")
    run(["make", "NVMEV_PROFILE=fast24", "-j4"], a.out / "build.log")
    helper = a.out / "nvme_hint"
    run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", ROOT / "evaluation_onfi_fast/nvme_hint.c",
         "-o", helper], a.out / "helper-build.log")
    reader = a.out / "read_pass"
    if a.collision_probe:
        probe = a.out / "collision_probe"
        run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", ROOT / "evaluation_onfi_fast/collision_probe.c",
             "-o", probe], a.out / "probe-build.log")
    elif a.timer == "aio":
        if a.iodepth > 256:
            raise RuntimeError("AIO pass supports QD up to 256")
        run(["cc", "-O2", "-Wall", "-Wextra", "-Werror", ROOT / "evaluation_onfi_fast/read_pass.c",
             "-o", reader], a.out / "reader-build.log")
    module_loaded = False
    try:
        for item in plan:
            folder = a.out / f"r{item['repeat']}" / item["group"] / item["case"]
            folder.mkdir(parents=True)
            print(f"{item['group']} {item['case']} r{item['repeat']}", flush=True)
            before_devices = namespaces()
            log_start = capture(["dmesg"])
            run(["insmod", ROOT / "nvmev.ko", "memmap_start=8G", "memmap_size=16G",
                 "cpus=" + a.cpus, f"onfi_collision={item['onfi']}",
                 f"fast_placement={item['placement']}"], folder / "insmod.log")
            module_loaded = True
            device = None
            for _ in range(100):
                found = namespaces() - before_devices
                if len(found) == 1:
                    device = verify_device(found.pop())
                    break
                if len(found) > 1:
                    raise RuntimeError("multiple unexpected namespaces appeared")
                time.sleep(0.1)
            if not device:
                raise RuntimeError("NVMeVirt namespace did not appear")
            if not a.module_smoke:
                iolog = folder / "read.iolog"
                run(["taskset", "-c", str(a.host_cpu), helper, device, item["case"],
                     str(item["seed"]), iolog, str(a.random_max_units)],
                    folder / "construction.json", timeout=1800)
                if a.collision_probe:
                    from summarize import stats, delta
                    counters(folder / "probe.before.stats")
                    run(["taskset", "-c", str(a.host_cpu), probe, iolog], folder / "probe.json")
                    counters(folder / "probe.after.stats")
                    measured = json.loads((folder / "probe.json").read_text())
                    if measured["completed"] != 16384 or not measured["verified"]:
                        raise RuntimeError("incomplete collision probe")
                    diff = delta(stats(folder / "probe.after.stats"), stats(folder / "probe.before.stats"))
                    if not diff["reads"] or not diff["programs"]:
                        raise RuntimeError("probe did not exercise NAND reads and programs")
                    if bool(diff["onfi_events"]) != bool(item["onfi"]):
                        raise RuntimeError("ONFI positive control counter did not match switch")
                for read in range(1, item["reads"] + 1):
                    counters(folder / f"read{read}.before.stats")
                    output = folder / f"read{read}.json"
                    if a.timer == "aio":
                        run(["taskset", "-c", str(a.host_cpu), reader, iolog, str(a.iodepth)], output)
                        measured = json.loads(output.read_text())
                        if (measured["io_bytes"] != 8388608 or measured["completed"] != 256
                                or not measured["verified"]):
                            raise RuntimeError("incomplete AIO pass")
                    else:
                        run(["taskset", "-c", str(a.host_cpu), "fio", "--name=fast24-read", "--ioengine=libaio", "--direct=1",
                         "--thread=1", "--numjobs=1", "--iodepth=" + str(a.iodepth),
                         "--read_iolog=" + str(iolog), "--replay_no_stall=1", "--readonly",
                         "--lat_percentiles=1", "--percentile_list=50:95:99:99.9",
                         "--output-format=json", "--output=" + str(output)], folder / f"read{read}.log")
                        check_fio(output)
                    counters(folder / f"read{read}.after.stats")
            counters(folder / "final.stats")
            run(["rmmod", "nvmev"], folder / "rmmod.log")
            module_loaded = False
            log_end = capture(["dmesg"])
            # dmesg may wrap; keep the complete post-run buffer if prefix no longer matches.
            delta = log_end[len(log_start):] if log_end.startswith(log_start) else log_end
            (folder / "dmesg.log").write_text(delta)
            validate_log(folder / "dmesg.log")
            (folder / "case.json").write_text(json.dumps(item | {"validated": True}, indent=2))
            if a.module_smoke:
                break
        manifest["status"] = "passed"
    except BaseException as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        if module_loaded:
            # The namespace is exclusively ours; no filesystem is mounted by this suite.
            subprocess.run(["rmmod", "nvmev"], check=False)
        (a.out / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError, OSError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
