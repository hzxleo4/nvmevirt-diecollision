#!/usr/bin/env python3
"""Ordinary fio random I/O on fresh 16 GiB NVMeVirt namespaces, ONFI A/B."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from runner import ROOT, GROUPS, capture, counters, namespaces, run, validate_log, verify_device
from summarize import stats, delta

CASES = {f"4k-r{r}-qd32": (4, r, 32) for r in (100, 0, 70, 50, 30)}
CASES.update({"4k-r50-qd1": (4, 50, 1), "32k-r50-qd32": (32, 50, 32),
              "32k-r50-qd1": (32, 50, 1)})
PATTERN = "0xa55a5aa5"


def save(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def checked_job(path, expected_bytes):
    data = json.loads(path.read_text())
    if len(data.get("jobs", [])) != 1 or data["jobs"][0]["error"]:
        raise RuntimeError(f"fio failed: {path}")
    job = data["jobs"][0]
    if sum(job[k]["io_bytes"] for k in ("read", "write")) != expected_bytes:
        raise RuntimeError(f"incomplete fio transfer: {path}")
    return job


def fio(folder, phase, device, host_cpu, size, amount, bs, qd, rw, seed, read_pct=50, verify=False):
    args = ["taskset", "-c", str(host_cpu), "/usr/bin/fio", "--name=" + phase,
            "--filename=" + device, "--ioengine=libaio", "--direct=1", "--numjobs=1",
            f"--iodepth={qd}", f"--bs={bs}", f"--size={size}", f"--io_size={amount}",
            "--rw=" + rw, f"--rwmixread={read_pct}", "--randrepeat=1", "--allrandrepeat=1",
            f"--randseed={seed}", "--random_generator=tausworthe64", "--norandommap=1",
            "--buffer_pattern=" + PATTERN, "--refill_buffers=0", "--group_reporting=1",
            "--output-format=json", "--output=" + str(folder / f"{phase}.json"),
            "--eta=never", "--exitall_on_error=1", "--allow_file_create=0"]
    if verify:
        args += ["--verify=pattern", "--verify_pattern=" + PATTERN, "--verify_fatal=1"]
    save(folder / f"{phase}.command.json", args)
    counters(folder / f"{phase}.before.stats")
    start = time.monotonic()
    with (folder / f"{phase}.log").open("w") as log, (folder / f"{phase}.telemetry.jsonl").open("w") as telemetry:
        proc = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        next_sample = 0
        try:
            while proc.poll() is None:
                elapsed = time.monotonic() - start
                if elapsed > 300:
                    raise RuntimeError("fio timeout")
                if elapsed >= next_sample:
                    telemetry.write(json.dumps({"elapsed_s": elapsed, "stats": Path("/proc/nvmev/debug").read_text()}) + "\n")
                    telemetry.flush()
                    next_sample = elapsed + 1
                try:
                    proc.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            if proc.returncode:
                raise RuntimeError(f"fio process failed: {folder}/{phase}")
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
    wall = time.monotonic() - start
    counters(folder / f"{phase}.after.stats")
    job = checked_job(folder / f"{phase}.json", amount)
    run(["nvme", "flush", device], folder / f"{phase}.flush.log")
    counters(folder / f"{phase}.drained.stats")
    save(folder / f"{phase}.timing.json", {"process_wall_s": wall,
         "process_and_drain_s": time.monotonic() - start, "fio_job_runtime_ms": job["job_runtime"]})
    save(folder / f"{phase}.counters.json", delta(stats(folder / f"{phase}.after.stats"), stats(folder / f"{phase}.before.stats")))
    save(folder / f"{phase}.drain_counters.json", delta(stats(folder / f"{phase}.drained.stats"), stats(folder / f"{phase}.after.stats")))
    return job


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan-only", action="store_true")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--cases", nargs="+", choices=CASES, default=list(CASES))
    ap.add_argument("--groups", nargs="+", choices=GROUPS, default=["A", "B"])
    ap.add_argument("--infer-overwrite", action="store_true",
                    help="opt-in NVMeVirt raw-LBA adapter for FAST overwrite affinity")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--working-mib", type=int, default=2048)
    ap.add_argument("--io-mib", type=int, default=2048)
    ap.add_argument("--cpus", default="7,8,9,10")
    ap.add_argument("--host-cpu", type=int, default=3)
    ap.add_argument("--out", type=Path, default=ROOT / "evaluation_onfi_fast/results" /
                    datetime.datetime.now(datetime.timezone.utc).strftime("fio-onfi-%Y%m%dT%H%M%SZ"))
    a = ap.parse_args()
    if a.smoke:
        a.repeats, a.working_mib, a.io_mib = 1, 16, 32
    if min(a.repeats, a.working_mib, a.io_mib) < 1 or a.working_mib + a.io_mib > 8192:
        ap.error("positive sizes required; this no-GC suite caps total fill+I/O at 8 GiB")
    if len(set(a.groups)) != len(a.groups):
        ap.error("groups must be unique")
    plan = [{"repeat": r, "case": c, "group": g, "onfi": GROUPS[g][0], "placement": GROUPS[g][1], "seed": 20261026+r,
             "bs_kib": CASES[c][0], "read_percent": CASES[c][1], "qd": CASES[c][2]}
            for r in range(1, a.repeats+1) for c in a.cases
            for g in a.groups[(r-1)%len(a.groups):] + a.groups[:(r-1)%len(a.groups)]]
    if a.plan_only:
        print(json.dumps({"working_mib": a.working_mib, "io_mib": a.io_mib,
                          "infer_overwrite": a.infer_overwrite, "plan": plan}, indent=2))
        return
    if os.geteuid() or "memmap=16G$8G" not in Path("/proc/cmdline").read_text().split():
        raise RuntimeError("root and 16 GiB boot reservation required")
    if Path("/sys/module/nvmev").exists():
        raise RuntimeError("refusing existing nvmev module")
    cpus = [int(c) for c in a.cpus.split(",")]
    if a.host_cpu in cpus or len(set(cpus)) != len(cpus):
        raise RuntimeError("application and emulator CPUs must be distinct")
    a.out = a.out.resolve()
    if not a.out.is_relative_to(ROOT / "evaluation_onfi_fast/results"):
        raise RuntimeError("output must be inside evaluation_onfi_fast/results")
    a.out.mkdir(parents=True, exist_ok=False)
    manifest = {"suite": "fio_random_fast" if a.infer_overwrite or any(i["placement"] for i in plan) else "fio_random_onfi",
                "status": "running", "smoke": a.smoke,
                "git_head": capture(["git", "rev-parse", "HEAD"]), "git_status": capture(["git", "status", "--porcelain"]),
                "kernel": capture(["uname", "-r"]), "fio": capture(["/usr/bin/fio", "--version"]),
                "physical_bytes": 16*1024**3, "working_bytes": a.working_mib*1024**2,
                "io_bytes": a.io_mib*1024**2, "fast_placement": any(i["placement"] for i in plan),
                "groups": a.groups, "infer_overwrite": a.infer_overwrite,
                "cpus": a.cpus, "host_cpu": a.host_cpu, "plan": plan,
                "notes": ["ordinary uniform random fio requests, no die selection or hints",
                          "fixed I/O volume; no time_based or steady-state claim",
                          "fresh sequential prefill and explicit NVMe FLUSH before measurement",
                          "post-test full-range constant-pattern verification is outside measurement",
                          "constant pattern verifies bytes but does not detect aliases between identically filled LBAs",
                          "measured fio counters and final explicit FLUSH counters are separate"]}
    sources = ("evaluation_onfi_fast/run_fio.py", "fast24_ftl.c", "ssd.c", "ssd_config.h", "onfi_model.h", "admin.c", "Kbuild")
    manifest["source_sha256"] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}
    manifest["notes"].append("Raw overwrite inference applies only to mapped LBAs; it does not infer file append/adjacency")
    save(a.out / "manifest.json", manifest)
    try:
        run(["make", "NVMEV_PROFILE=fast24", "-j4"], a.out / "build.log")
        for item in plan:
            folder = a.out / f"r{item['repeat']}" / item["group"] / item["case"]
            folder.mkdir(parents=True)
            print(f"START r{item['repeat']} {item['group']} {item['case']}", flush=True)
            loaded = False
            log_start = capture(["dmesg"])
            try:
                before = namespaces()
                run(["insmod", ROOT / "nvmev.ko", "memmap_start=8G", "memmap_size=16G", "cpus="+a.cpus,
                     f"onfi_collision={item['onfi']}", f"fast_placement={item['placement']}",
                     f"fast_infer_overwrite={int(a.infer_overwrite)}"], folder / "insmod.log")
                loaded = True
                for _ in range(100):
                    found = namespaces()-before
                    if len(found) == 1:
                        device = verify_device(found.pop())
                        break
                    if len(found) > 1:
                        raise RuntimeError("ambiguous new namespaces")
                    time.sleep(.1)
                else:
                    raise RuntimeError("new namespace not found")
                capacity = int(capture(["blockdev", "--getsize64", device]))
                if manifest["working_bytes"] > capacity:
                    raise RuntimeError("working set exceeds namespace")
                save(folder / "device.json", {"device": device, "logical_bytes": capacity, "model": "NVMeVirt_FAST24"})
                run(["udevadm", "settle", "--timeout=30"], folder / "udev-settle.log")
                fio(folder, "prefill", device, a.host_cpu, manifest["working_bytes"], manifest["working_bytes"],
                    "1m", 32, "write", item["seed"])
                # Wait out fresh-device discovery reads before taking the
                # measured baseline. Never stop global udev/desktop services.
                previous, quiet = None, 0
                for _ in range(30):
                    snapshot = Path("/proc/nvmev/debug").read_text()
                    quiet = quiet + 1 if snapshot == previous else 0
                    previous = snapshot
                    if quiet == 3:
                        break
                    time.sleep(.5)
                else:
                    raise RuntimeError("virtual device did not become idle after prefill")
                rw = "randread" if item["read_percent"] == 100 else "randwrite" if not item["read_percent"] else "randrw"
                job = fio(folder, "measure", device, a.host_cpu, manifest["working_bytes"], manifest["io_bytes"],
                          f"{item['bs_kib']}k", item["qd"], rw, item["seed"], item["read_percent"])
                if any(job[k]["io_bytes"] == 0 for k in ("read", "write") if
                       (k == "read" and item["read_percent"] > 0) or (k == "write" and item["read_percent"] < 100)):
                    raise RuntimeError("missing requested I/O direction")
                fio(folder, "verify", device, a.host_cpu, manifest["working_bytes"], manifest["working_bytes"],
                    "128k", 32, "read", item["seed"], verify=True)
                counters(folder / "final.stats")
                fields = dict(x.split("=") for x in next(l for l in (folder / "final.stats").read_text().splitlines()
                                                        if l.startswith("fast24 ")).split()[1:])
                if (int(fields["onfi"]) != item["onfi"] or int(fields["placement"]) != item["placement"] or
                        int(fields["infer_overwrite"]) != a.infer_overwrite or any(int(fields[k]) for k in
                        ("rejected", "append_hints", "overwrite_hints", "applied"))):
                    raise RuntimeError("feature switch or I/O validation failure")
                expected = job["write"]["io_bytes"] // 4096 if a.infer_overwrite else 0
                if (int(fields["inferred_candidates"]) != expected or
                        int(fields["inferred_applied"]) != (expected if item["placement"] else 0)):
                    raise RuntimeError("raw overwrite inference did not match measured writes")
                if item["placement"] and expected and not int(fields["inferred_changed"]):
                    raise RuntimeError("FAST inference never changed the allocator die choice")
                if stats(folder / "final.stats")["gc"]:
                    raise RuntimeError("GC occurred; not a valid no-GC experiment")
            finally:
                if loaded:
                    run(["rmmod", "nvmev"], folder / "rmmod.log")
                end = capture(["dmesg"])
                (folder / "dmesg.log").write_text(end[len(log_start):] if end.startswith(log_start) else end)
                validate_log(folder / "dmesg.log")
            save(folder / "case.json", item | {"validated": True})
            print(f"PASS r{item['repeat']} {item['group']} {item['case']}", flush=True)
        manifest["status"] = "passed"
    except BaseException as exc:
        manifest["status"], manifest["error"] = "failed", str(exc)
        raise
    finally:
        save(a.out / "manifest.json", manifest)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print("ERROR:", exc, file=sys.stderr)
        sys.exit(1)
