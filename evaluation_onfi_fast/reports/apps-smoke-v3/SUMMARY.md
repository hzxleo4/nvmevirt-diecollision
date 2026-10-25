# SQLite / Filebench：16 GiB ONFI 应用实验

原始结果：`evaluation_onfi_fast/results/apps-smoke-v3`；测试源码提交：`647a7d1f318997b788c93b9626f5cad12bf3aa51`。
状态：全部 6 个用例通过；正式实验：否（smoke）。
A：ONFI 关；B：ONFI 开。两组 FAST placement 均关闭，主机内核未修改。
协议和适配说明见 [APPLICATIONS.zh-CN.md](../../APPLICATIONS.zh-CN.md)。

SQLite：100 条约 16 KiB 记录，逐条插入后追加并同步 100 KiB dummy；
每次构造后做 1 次冷缓存 SELECT。Filebench：100 个初始 128 KiB 文件，
10 线程，32/16 KiB 追加，累计 32 MiB 后同步写回，direct I/O 读取 2 秒。
Filebench 采用固定追加量适配容量，**不是论文的不限量追加 60 秒**。

## 按独立重建汇总

均值 ± 样本标准差；SQLite 先对每次重建的冷读取均值，再对独立重建汇总。
SQLite 的延迟是一次全表 SELECT 用时；Filebench 的延迟是一次 readwholefile 的平均用时，二者不可直接比较。
Filebench 原始平均延迟精度为 0.1 ms；这套配置未采集应用 P99。
Filebench 构造时间包括文件创建、追加、进程开销及末尾写回；SQLite 为辅助程序内部的完整构造时间。

| 工作负载 | 组 | 独立重建 | 构造秒 | 读取吞吐 | 单位 | 读取延迟 ms |
|---|---|---:|---:|---:|---|---:|
| fileserver | A | 1 | 3.160 ± 0.000 | 2157.60 ± 0.00 | MiB/s | 2.000 ± 0.000 |
| fileserver | B | 1 | 3.156 ± 0.000 | 2083.20 ± 0.00 | MiB/s | 2.100 ± 0.000 |
| fileserver_small | A | 1 | 3.156 ± 0.000 | 1785.20 ± 0.00 | MiB/s | 2.400 ± 0.000 |
| fileserver_small | B | 1 | 3.167 ± 0.000 | 1741.50 ± 0.00 | MiB/s | 2.500 ± 0.000 |
| sqlite | A | 1 | 0.048 ± 0.000 | 25515.14 ± 0.00 | records/s | 3.919 ± 0.000 |
| sqlite | B | 1 | 0.046 ± 0.000 | 28871.67 ± 0.00 | records/s | 3.464 ± 0.000 |

| 工作负载 | 构造用时变化 B/A | 读取吞吐变化 B/A | 读取延迟变化 B/A |
|---|---:|---:|---:|
| fileserver | -0.12% | -3.45% | +5.00% |
| fileserver_small | +0.35% | -2.45% | +4.17% |
| sqlite | -3.40% | +13.16% | -11.63% |

这些是观测到的均值差值，不是已经隔离出的 ONFI 因果效应；需结合计数器和逐轮布局差异判断。

## ONFI / NAND 计数

计数为各行全部重复的总和；累计等待不是应用墙钟损失，不能直接换算性能降幅。
构造计数包含最终写回。只统计测量窗口，文件校验和 mkfs 不包含在内。

| 工作负载 | 组 | 阶段 | ONFI 次数 | 累计等待 ms | NAND program | NAND read | GC 次数 |
|---|---|---|---:|---:|---:|---:|---:|
| fileserver | A | 构造 | 0 | 0.000000 | 1438 | 1 | 0 |
| fileserver | A | 读取 | 0 | 0.000000 | 0 | 238941 | 0 |
| fileserver | B | 构造 | 0 | 0.000000 | 1436 | 10 | 0 |
| fileserver | B | 读取 | 0 | 0.000000 | 0 | 238425 | 0 |
| fileserver_small | A | 构造 | 0 | 0.000000 | 1432 | 1 | 0 |
| fileserver_small | A | 读取 | 0 | 0.000000 | 0 | 284206 | 0 |
| fileserver_small | B | 构造 | 0 | 0.000000 | 1434 | 1 | 0 |
| fileserver_small | B | 读取 | 0 | 0.000000 | 0 | 287124 | 0 |
| sqlite | A | 构造 | 0 | 0.000000 | 403 | 1 | 0 |
| sqlite | A | 读取 | 0 | 0.000000 | 0 | 168 | 0 |
| sqlite | B | 构造 | 0 | 0.000000 | 403 | 1 | 0 |
| sqlite | B | 读取 | 0 | 0.000000 | 0 | 168 | 0 |

**读取阶段 ONFI 等待均为零。读取吞吐的 A/B 差异不能归因为 ONFI 阻塞。**
这些工作负载按论文先构造再读；读阶段 NAND program 数和 GC 数见表。

构造阶段也未观测到 ONFI 等待，构造用时差异同样不能作为 ONFI 罚时证据。

开启组读取 ONFI 等待为零的应用：fileserver、fileserver_small、sqlite。
这些应用的读取均值差异不能解释为 ONFI 直接阻塞；若开启组更快，也不能据此宣称 ONFI 会加速。
Filebench 并发构造可能产生不同布局，下表的每 MiB NAND read 次数用于核对这种差异。

## 全部独立重建结果

NAND read/MiB = NAND read 次数 ÷ FTL 已映射的逻辑读页数 × 256（4 KiB 页）。
它反映每 MiB 逻辑读需要多少次 NAND read，包含元数据访问；不是闪存传输字节的放大率。
不同独立构造的布局可能不同，需结合这个指标解释读取吞吐差异。

| 工作负载 | 组 | 轮次 | 构造 s | 数据 MiB | 读取吞吐 | 单位 | 读取延迟 ms | NAND read/MiB | 构造 ONFI | 读取 ONFI |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| sqlite | A | 1 | 0.048 | 1.625 | 25515.14 | records/s | 3.919 | 103.38 | 0 | 0 |
| sqlite | B | 1 | 0.046 | 1.625 | 28871.67 | records/s | 3.464 | 103.38 | 0 | 0 |
| fileserver | A | 1 | 3.160 | 44.480 | 2157.60 | MiB/s | 2.000 | 55.31 | 0 | 0 |
| fileserver | B | 1 | 3.156 | 44.402 | 2083.20 | MiB/s | 2.100 | 57.16 | 0 | 0 |
| fileserver_small | A | 1 | 3.156 | 44.297 | 1785.20 | MiB/s | 2.400 | 79.50 | 0 | 0 |
| fileserver_small | B | 1 | 3.167 | 44.336 | 1741.50 | MiB/s | 2.500 | 82.32 | 0 | 0 |

## 每一次读取

| 工作负载 | 组 | 轮次 | 读序号 | 吞吐 | 单位 | 延迟 ms | ONFI 次数 | NAND program | NAND read |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| sqlite | A | 1 | 1 | 25515.14 | records/s | 3.919 | 0 | 0 | 168 |
| sqlite | B | 1 | 1 | 28871.67 | records/s | 3.464 | 0 | 0 | 168 |
| fileserver | A | 1 | 1 | 2157.60 | MiB/s | 2.000 | 0 | 0 | 238941 |
| fileserver | B | 1 | 1 | 2083.20 | MiB/s | 2.100 | 0 | 0 | 238425 |
| fileserver_small | A | 1 | 1 | 1785.20 | MiB/s | 2.400 | 0 | 0 | 284206 |
| fileserver_small | B | 1 | 1 | 1741.50 | MiB/s | 2.500 | 0 | 0 | 287124 |

## 数据与验证

- [全部构造数据](construction.csv)：含实际文件增长、报告追加字节数、计数器及写回时间。
- [全部读取数据](reads.csv)、[独立重建](trials.csv)、[聚合](aggregate.csv)、[A/B 差值](comparisons.csv)。
- [源码与运行配置](source_manifest.json)。
- [原始日志和计数器归档](raw-results.tar.gz)，逐文件校验值见 [raw_inventory.csv](raw_inventory.csv)。
- SQLite 所有字段、主键顺序和 integrity_check 通过；Filebench 读取前后大小及 SHA256 一致。
- 应用无错误退出、无被拒绝的 NVMe I/O 或主机 FAST 提示；VM 参数已恢复。
- 标准差反映独立构造的离散程度，不是显著性检验；Filebench 并发轨迹未逐请求锁定。
- SQLite filefrag 记录为 100–100 个 extent；论文报告 DoF 5,005，不能声称文件布局完全一致。
