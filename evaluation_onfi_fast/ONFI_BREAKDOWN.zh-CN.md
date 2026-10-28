# ONFI 开关：fio 等待路径与阻塞模式

本轮只比较 A（ONFI 关）与 B（ONFI 开），两组的 `fast_placement=0`、
`fast_infer_overwrite=0`。沿用 [fio 协议](FIO.zh-CN.md)：16 GiB 物理预留，
2 GiB 工作集，顺序预填充并 flush，每次完成固定 2 GiB 测量 I/O，随后 flush、
全范围模式验证、卸载。统计阶段不得出现 GC。保持现有时序和分配规则。

## 矩阵

- 原来的八种配置，两组各三轮。
- 4 KiB、读写各半额外加入 QD=2/4/8/16/64，形成 QD=1/2/4/8/16/32/64 扫描。
- 4 KiB 与 32 KiB、读写各半、QD32 加入完全关闭诊断的对照；同配置同轮次穿插运行，
  每轮改变开启/关闭统计的先后顺序。用实测结果检查观察开销。
- 共 78 项带统计正式实验和 12 项无统计对照；每项独立重建，相同种子与完成字节数。

## 观察开关

`onfi_diagnostics=1` 在加载时分配统计内存；默认关闭。
`onfi_diag_active=1` 仅控制是否记录，不改变排队/时序，也不会重置排队状态。
runner 只在测量 fio 的进程窗口开启观察，结束后关闭；预填充、最终 flush 和验证不计入分解。
应用吞吐/延迟仍使用 fio 内部计时。进程窗口中的后台读取仍保留，不能当作严格只包含 fio 请求。

`onfi_trace_skip=2048 onfi_trace_limit=512`：每个通道跳过前 2048 个被观察的 NAND 命令，
随后保留连续 512 条完整事件；冒烟 skip=0。这是明确界定的早期窗口，不是整场均匀抽样，
用于检查时间线和局部序列。所有操作的总计数、阶段时间和直方图覆盖整个观察窗口。
`/proc/nvmev/debug` 提供聚合信息；`/proc/nvmev/onfi_trace` 仅在 fio 结束后读取。

## 分解口径

每个 NAND read/program 的 `end - start` 必须严格等于以下八项之和：

| 字段 | 含义 |
|---|---|
| `lun_ns` | 等待本 die 已预订操作完成；另按上一操作是 read/program/其他分类 |
| `input_ns` | 在本 die 可用后，等待同 target 已预订 program 命令/数据输入结束；A/B 都保留 |
| `onfi_ns` | program 在前两项等待之后，为未完成的读数据输出增加的等待；只有 B 实施 |
| `array_ns` | 本次 NAND sensing 或 program 的配置时延 |
| `channel_late_ns` | 通道模型发现请求时间已落后于模拟器处理时钟而补齐的时间 |
| `channel_queue_ns` | 通道信用模型在配置传输成本之外增加的排队时间 |
| `channel_service_ns` | 通道模型配置的传输成本，包含该模型的固件传输开销 |
| `pcie_tail_ns` | 读数据通道传输结束后仍暴露在完成路径上的 PCIe 尾部时间；不是全部 PCIe 工作量 |

每类分别给出平均每条 NAND 命令的时间；不能把不同操作/通道的累计等待相加后解释为墙钟损失。
它们也不是 fio 端到端延迟的逐项分解：后者还含主机、固件入口、FTL 依赖、提交/回收等。
主机 read/write 的设备模型延迟、写缓冲重试次数、读触发部分页 flush 次数另列。
缓冲重试次数表示重试尝试，不能当作独立受阻写请求数；非 FUA 写仍在进入缓冲后完成。

## ONFI 内部等待与 pattern

每个触发事件记录等待者的 channel/LUN、阻塞它的读的 LUN 与序号、读的 sensing 起止和数据输出结束时刻。
再将 `onfi_ns` 按阻塞读的阶段切为：

1. 对侧读尚未进入 sensing 的排队时间；
2. 对侧读正在 sensing 的时间；
3. 对侧读 sensing 后的数据输出阶段（包含通道排队）。

三项严格相加等于直接 ONFI 等待。这描述的是当前模拟器的“已预订读完成屏障”：
它会等待已经排入未来时刻的读，不只等待此刻已经在输出数据的读。
因此结果包含调度顺序和排队放大，不是 ONFI 规范规定的一项固定额外时延。
同 die 的既有忙时间先行计入 `lun_ns`；被其遮蔽的等待不会重复记入 ONFI。

关 ONFI 时也统计当前调度轨迹上存在的局部等待机会（`opportunity_*`），但不增加完成时间。
这不是打开 ONFI 后的完整反事实轨迹，不可当作节省的墙钟时间。

ONFI、同 die 等待与 NAND 总时延的直方图使用以微秒为单位的 2 倍递增桶；
零等待单独由总请求数与等待事件数得到。分位数只能报告所在区间，不能伪装成精确分位点。

## 复跑

```bash
./tests/run.sh
sudo python3 evaluation_onfi_fast/run_fio.py --diagnostics --qd-sweep --diagnostic-controls 4k-r50-qd32 32k-r50-qd32 --out evaluation_onfi_fast/results/new-onfi-breakdown
python3 evaluation_onfi_fast/summarize_onfi_breakdown.py evaluation_onfi_fast/results/new-onfi-breakdown --output evaluation_onfi_fast/reports/new-onfi-breakdown
```

单元测试验证分解守恒、同 die 忙时间遮蔽 ONFI、跨 die 阻塞、OFF 观察和桶边界；
runner 对每项真实设备测试再次核对阶段之和、与原 ONFI 计数的一致性、NAND 操作数和事件时间线。
