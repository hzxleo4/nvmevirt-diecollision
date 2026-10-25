# 在普通 fio 上实际启用 FAST 覆盖策略

普通 fio/libaio 不发送 FAST '24 的 NVMe 文件提示。原有
`fast_placement=1` 只消费显式提示，单独打开该开关不会改变普通 fio 的放置。
`fio-fast-switch-smoke-v1` 对此进行了真实设备验证：开关开启，实际策略应用为零。

本次为预填充后的 raw fio 添加默认关闭的设备内适配：

```text
fast_infer_overwrite=1
```

NVMeVirt 从现有 FTL 映射识别“这个 LBA 已经写过”，对没有显式提示的覆盖写
提供覆盖属性，再由 `fast_placement` 决定是否执行 FAST 的“保持原 die”规则。
不修改 fio、主机内核或文件系统。它只适用于可以从 LBA 映射识别的覆盖，
**不推断文件身份、追加或相邻文件块**，不等于完整 FAST 文件系统提示路径。
写入未映射 LBA 仍走原分配器；显式追加/覆盖提示优先。关闭适配开关保留原行为。

## 四组设计

| 组 | ONFI | FAST placement | 设备内覆盖识别 |
|---|---:|---:|---:|
| A | 关 | 关 | 开 |
| B | 开 | 关 | 开 |
| C | 开 | 开 | 开 |
| D | 关 | 开 | 开 |

所有组都做相同覆盖识别和候选计数，只有 C/D 应用放置策略。
每组同一轮的读写字节数与随机种子一致，组别顺序按轮次轮换。
重新运行八种原 fio 配置、四组、三轮，共 96 个用例；不把旧批次 A/B
与新批次 C/D 拼接成一个同批对照。其余条件沿用 [FIO.zh-CN.md](FIO.zh-CN.md)：
16 GiB 物理预留、2 GiB 顺序预填充工作集、显式 flush、2 GiB 固定测量 I/O、
direct/libaio、单 job、测量后完整模式校验，无 GC。

比较 C/B 看 ONFI 开启时 FAST 的效果，D/A 看无 ONFI 时的效果；
B/A 与 C/D 分别量化 FAST 关/开时的 ONFI 吞吐差异。
FAST 解决的是页到 die 的放置问题，并未修改 ONFI 限制；不能预设它会消除 collision。

## 策略计数与验证

`/proc/nvmev/debug` 新增：

- `infer_overwrite`：设备内识别开关。
- `inferred_candidates`：没有显式提示且已有映射的 4 KiB 覆盖页数。
- `inferred_applied`：其中实际采用 FAST 原 die 选择的页数；A/B 必须为零。
- `inferred_changed`：选择的 die 不同于当时普通分配游标的页数；不是整段反事实重放的差异页数。

原 `append_hints`、`overwrite_hints`、`applied` 仍只统计显式主机提示，避免把设备识别
伪装成主机提示。所有写入均落在已预填充范围，候选数应等于 fio 写入字节数 / 4096，
C/D 的实际应用数也应相等；runner 和汇总脚本都验证这一条件。

实际 FTL 单元测试覆盖默认关闭、策略关闭、未映射地址、显式提示优先，以及
推断覆盖下反复 GC、部分页填充、映射/反向映射与缓冲计数；运行 ASAN/UBSAN/LSAN。
测量后的固定模式校验不能检测内容相同 LBA 之间的别名，映射不变量由 FTL 测试补充检查。

## 复跑

```bash
./tests/run.sh
sudo python3 evaluation_onfi_fast/run_fio.py --smoke --groups B C --cases 4k-r50-qd32 --out evaluation_onfi_fast/results/new-fast-switch-smoke
sudo python3 evaluation_onfi_fast/run_fio.py --smoke --groups A B C D --infer-overwrite --out evaluation_onfi_fast/results/new-fast-infer-smoke
sudo python3 evaluation_onfi_fast/run_fio.py --groups A B C D --infer-overwrite --out evaluation_onfi_fast/results/new-fio-fast
python3 evaluation_onfi_fast/summarize_fio.py evaluation_onfi_fast/results/new-fio-fast --output evaluation_onfi_fast/reports/new-fio-fast
```

三个模块开关均为加载时参数，卸载/重载后切换；不在有在途 I/O 时动态修改。

## 已完成结果

[正式四组报告](reports/fio-fast-16g-v1/SUMMARY.md)：96 项全部通过，三轮独立重建。
吞吐、读写平均/P99、ONFI 等待、实际策略应用、每轮原始日志均已归档。
效果随负载而变，包含小幅提升和性能下降，完整比较见
[中文结果分析](RESULTS.zh-CN.md#常规-fio同时开启-onfi-与-fast-覆盖策略)。
