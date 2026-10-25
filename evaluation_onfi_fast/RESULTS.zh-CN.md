# 16 GiB：ONFI 限制与 FAST ’24 放置策略

当前结果来自 NVMeVirt 设备级方法复现。主机仍为原来的
`6.8.0-138-generic`；没有安装或切换内核。论文的完整
SQLite/Filebench 文件系统端到端复现尚未完成。

## 实现与开关

`make NVMEV_PROFILE=fast24` 编译实验设备。两项功能独立控制：

| 组别 | `onfi_collision` | `fast_placement` |
|---|---:|---:|
| A | 0 | 0 |
| B | 1 | 0 |
| C | 1 | 1 |
| D | 0 | 1 |

开关是加载模块时的参数，不需要重新编译；切换时卸载并重新加载，
重新构造测试数据。当前不支持带着在途请求实时切换。
四组共享分配器、4 MiB 写缓冲、GC 和时序参数，比较的是两个因素，
不是 CLSSD 整个 FTL 与 FAST 整个 FTL 的架构对比。

ONFI 实现对应 CLSSD 所讨论的目标内页寄存器限制：同一 target
存在未完成 NAND 数据输出的读时，另一 die 的 program 数据输入需要等待。
等待到读数据传输完成，而不只是 sensing 完成。另一 die 的读仍可与已经
开始的 tPROG 重叠。本实验明确采用 4 个通道、每通道 1 个 target、
每 target 2 个 LUN 的拓扑；这是结果适用的硬件模型。

FAST 实现包括：追加时从文件前一块所在 die 的后继 die 开始放置；
覆盖时保持各映射页原来的 die。测试程序使用作者的 NVMe 提示编码，
两项策略在 NVMeVirt 内执行。原版主机不会自动为普通应用提供这些文件信息。

## FAST 论文布局的设备级实验

物理预留 16 GiB；逻辑容量为 16,054,972,416 字节，差额来自元数据和 OP。
每个目标 8 MiB，由 256 个 32 KiB 块组成。最坏干扰为 224 KiB；
随机干扰使用论文文字的 32 KiB–32 MiB 范围。作者公开脚本使用
32 KiB–1 MiB，脚本也提供该选项，但没有混合两种范围的结果。

每组每种布局独立构造 3 次，每次读取 10 遍，共 60 次构造、600 遍读取。
固定主机 CPU，采用 QD32、32 KiB 直接 AIO 读和纳秒计时；每遍完整
读取并核验 8 MiB。这里没有复现论文 ext4 路径及 1 MiB 应用 read
系统调用，因此绝对吞吐不能直接当作论文应用结果。

| 布局 | B：ONFI 开、FAST 关（MiB/s） | C：ONFI 开、FAST 开（MiB/s） | C/B |
|---|---:|---:|---:|
| 最坏追加 | 411.63 | 2690.75 | 6.54 倍 |
| 最坏覆盖 | 407.86 | 2601.53 | 6.38 倍 |
| 随机追加 | 2128.62 | 2590.97 | 1.22 倍 |
| 随机覆盖 | 2103.39 | 2588.27 | 1.23 倍 |

随机布局与连续布局的短读波动较明显；这里列的是样本均值，不能据此
宣称统计显著性。十遍重复读取不是十次独立布局构造。

构造阶段只有写，读阶段没有 program/GC；两阶段的 ONFI 等待计数均为零。
所以该工作负载中**没有测到由 ONFI 约束引发的等待开销**，A/B、C/D 的
小幅差异不能解释为 ONFI 损失。FAST 改善的是同 die 上读请求聚集造成的
串行化，这与 ONFI 读/program 页寄存器限制是不同的问题。

详细数据、标准差、每遍读数和图见
[正式报告](reports/main-16g-aio-v1/SUMMARY.md)及
[吞吐图](reports/main-16g-aio-v1/throughput.png)。测试源码提交为 `e6aecf9`。

## ONFI 生效验证：单独的诊断工作负载

为了验证“零等待”不是功能没生效，另做同 target、不同 die 的交错读写：
16,384 个 32 KiB 请求，QD64，读写各半，地址区间互不重叠。
每组 3 次。此项不是 FAST 论文的工作负载，不放入论文复现结果表。

| 组别 | 总吞吐（MiB/s，含最终 flush） | 3 次合计 ONFI 等待次数 |
|---|---:|---:|
| A | 1484.60 | 0 |
| B | 834.32 | 24,220 |
| C | 836.42 | 24,377 |
| D | 1478.42 | 0 |

在这个特定重叠模式下，B/A 吞吐下降 **43.80%**。该数字证明模型能产生
性能影响，不代表 SQLite、Filebench 或 CLSSD 全套工作负载都会下降这么多。
诊断写入没有文件提示，FAST 不改变其放置，因此 C 与 B 接近。

见[诊断报告](reports/onfi-positive-16g-v3/SUMMARY.md)。测试源码提交为
`cc4b58e`，清洁工作区运行，manifest 保存代码 SHA256。所有正式测试均完成
数据校验及内核错误日志检查，结束后已卸载虚拟设备。

## 复跑

```bash
./tests/run.sh
sudo ./evaluation_onfi_fast/run_all.sh --timer aio --repeats 3 --reads 10 --out evaluation_onfi_fast/results/new-main
python3 evaluation_onfi_fast/summarize.py evaluation_onfi_fast/results/new-main --output evaluation_onfi_fast/reports/new-main
python3 evaluation_onfi_fast/plot_results.py evaluation_onfi_fast/reports/new-main

sudo ./evaluation_onfi_fast/run_all.sh --collision-probe --repeats 3 --out evaluation_onfi_fast/results/new-probe
python3 evaluation_onfi_fast/summarize_probe.py evaluation_onfi_fast/results/new-probe --output evaluation_onfi_fast/reports/new-probe
```

脚本只操作本轮新建、型号核验为 `NVMeVirt_FAST24` 的虚拟 namespace。
原始结果留在本机 `evaluation_onfi_fast/results/`，汇总、图及运行清单纳入 Git。
