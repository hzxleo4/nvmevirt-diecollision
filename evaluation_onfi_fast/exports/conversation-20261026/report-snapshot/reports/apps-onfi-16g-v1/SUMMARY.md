# SQLite / Filebench：16 GiB ONFI 应用实验

原始结果：`evaluation_onfi_fast/results/apps-onfi-16g-v1`；测试源码提交：`a0a8c50067daaac1f2499c1a1edb836a5bd2ac96`。
状态：全部 18 个用例通过；正式实验：是。
A：ONFI 关；B：ONFI 开。两组 FAST placement 均关闭，主机内核未修改。
协议和适配说明见 [APPLICATIONS.zh-CN.md](../../../../../APPLICATIONS.zh-CN.md)。

SQLite：10,000 条约 16 KiB 记录，逐条插入后追加并同步 100 KiB dummy；
每次构造后做 10 次冷缓存 SELECT。Filebench：10,000 个初始 128 KiB 文件，
10 线程，32/16 KiB 追加，累计 4096 MiB 后同步写回，direct I/O 读取 60 秒。
Filebench 采用固定追加量适配容量，**不是论文的不限量追加 60 秒**。

## 按独立重建汇总

均值 ± 样本标准差；SQLite 先对每次重建的冷读取均值，再对独立重建汇总。
SQLite 的延迟是一次全表 SELECT 用时；Filebench 的延迟是一次 readwholefile 的平均用时，二者不可直接比较。
Filebench 原始平均延迟精度为 0.1 ms；这套配置未采集应用 P99。
Filebench 构造时间包括文件创建、追加、进程开销及末尾写回；SQLite 为辅助程序内部的完整构造时间。

| 工作负载 | 组 | 独立重建 | 构造秒 | 读取吞吐 | 单位 | 读取延迟 ms |
|---|---|---:|---:|---:|---|---:|
| fileserver | A | 3 | 7.480 ± 0.269 | 2131.13 ± 20.92 | MiB/s | 2.500 ± 0.000 |
| fileserver | B | 3 | 7.240 ± 0.041 | 2234.67 ± 256.08 | MiB/s | 2.400 ± 0.265 |
| fileserver_small | A | 3 | 7.544 ± 0.292 | 1758.20 ± 3.18 | MiB/s | 3.000 ± 0.000 |
| fileserver_small | B | 3 | 7.558 ± 0.356 | 1865.83 ± 113.67 | MiB/s | 2.867 ± 0.153 |
| sqlite | A | 3 | 3.254 ± 0.821 | 35602.16 ± 376.81 | records/s | 281.224 ± 3.307 |
| sqlite | B | 3 | 2.933 ± 0.771 | 35617.71 ± 175.11 | records/s | 281.215 ± 1.372 |

| 工作负载 | 构造用时变化 B/A | 读取吞吐变化 B/A | 读取延迟变化 B/A |
|---|---:|---:|---:|
| fileserver | -3.21% | +4.86% | -4.00% |
| fileserver_small | +0.19% | +6.12% | -4.44% |
| sqlite | -9.84% | +0.04% | -0.00% |

这些是观测到的均值差值，不是已经隔离出的 ONFI 因果效应；需结合计数器和逐轮布局差异判断。

## ONFI / NAND 计数

计数为各行全部重复的总和；累计等待不是应用墙钟损失，不能直接换算性能降幅。
构造计数包含最终写回。只统计测量窗口，文件校验和 mkfs 不包含在内。

| 工作负载 | 组 | 阶段 | ONFI 次数 | 累计等待 ms | NAND program | NAND read | GC 次数 |
|---|---|---|---:|---:|---:|---:|---:|
| fileserver | A | 构造 | 0 | 0.000000 | 517465 | 170 | 0 |
| fileserver | A | 读取 | 0 | 0.000000 | 0 | 22590866 | 0 |
| fileserver | B | 构造 | 9 | 1.586728 | 517463 | 194 | 0 |
| fileserver | B | 读取 | 0 | 0.000000 | 0 | 20725100 | 0 |
| fileserver_small | A | 构造 | 0 | 0.000000 | 517449 | 187 | 0 |
| fileserver_small | A | 读取 | 0 | 0.000000 | 0 | 26394894 | 0 |
| fileserver_small | B | 构造 | 2 | 0.290782 | 517449 | 211 | 0 |
| fileserver_small | B | 读取 | 0 | 0.000000 | 0 | 25632099 | 0 |
| sqlite | A | 构造 | 0 | 0.000000 | 121311 | 3 | 0 |
| sqlite | A | 读取 | 0 | 0.000000 | 3 | 474510 | 0 |
| sqlite | B | 构造 | 4 | 0.258193 | 121311 | 22 | 0 |
| sqlite | B | 读取 | 2 | 0.080057 | 3 | 474520 | 0 |

开启组读取 ONFI 等待为零的应用：fileserver、fileserver_small。
这些应用的读取均值差异不能解释为 ONFI 直接阻塞；若开启组更快，也不能据此宣称 ONFI 会加速。
Filebench 并发构造可能产生不同布局，下表的每 MiB NAND read 次数用于核对这种差异。

读取窗口虽无主机 WRITE、无 GC，仍有少量 NAND program。当前控制器报告 VWC=0，
syncfs 清理主机脏页并不保证触发显式 NVMe FLUSH；FTL 读到未满 32 KiB 页时会先补齐并 program。
这些计数保留在读阶段，没有移到构造阶段或过滤首遍读；详见每遍统计与 fast24_ftl.c 的 fast_read。

## 全部独立重建结果

NAND read/MiB = NAND read 次数 ÷ FTL 已映射的逻辑读页数 × 256（4 KiB 页）。
它反映每 MiB 逻辑读需要多少次 NAND read，包含元数据访问；不是闪存传输字节的放大率。
不同独立构造的布局可能不同，需结合这个指标解释读取吞吐差异。

| 工作负载 | 组 | 轮次 | 构造 s | 数据 MiB | 读取吞吐 | 单位 | 读取延迟 ms | NAND read/MiB | 构造 ONFI | 读取 ONFI |
|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| sqlite | A | 1 | 3.729 | 161.336 | 35678.31 | records/s | 280.406 | 97.96 | 0 | 0 |
| sqlite | B | 1 | 2.726 | 161.336 | 35761.54 | records/s | 279.971 | 97.96 | 4 | 1 |
| fileserver | A | 1 | 7.736 | 5346.312 | 2153.60 | MiB/s | 2.500 | 58.86 | 0 | 0 |
| fileserver | B | 1 | 7.248 | 5346.281 | 2530.20 | MiB/s | 2.100 | 39.35 | 3 | 0 |
| fileserver_small | A | 1 | 7.506 | 5346.156 | 1755.50 | MiB/s | 3.000 | 83.37 | 0 | 0 |
| fileserver_small | B | 1 | 7.196 | 5346.156 | 1849.20 | MiB/s | 2.900 | 77.33 | 2 | 0 |
| sqlite | B | 2 | 3.787 | 161.336 | 35422.72 | records/s | 282.687 | 97.97 | 0 | 0 |
| sqlite | A | 2 | 3.726 | 161.336 | 35193.09 | records/s | 284.864 | 97.96 | 0 | 0 |
| fileserver | B | 2 | 7.196 | 5346.250 | 2078.40 | MiB/s | 2.600 | 58.98 | 3 | 0 |
| fileserver | A | 2 | 7.200 | 5346.312 | 2127.60 | MiB/s | 2.500 | 58.89 | 0 | 0 |
| fileserver_small | B | 2 | 7.571 | 5346.141 | 1986.90 | MiB/s | 2.700 | 69.12 | 0 | 0 |
| fileserver_small | A | 2 | 7.853 | 5346.141 | 1761.70 | MiB/s | 3.000 | 83.40 | 0 | 0 |
| sqlite | A | 3 | 2.305 | 161.336 | 35935.09 | records/s | 278.403 | 97.96 | 0 | 0 |
| sqlite | B | 3 | 2.287 | 161.336 | 35668.88 | records/s | 280.988 | 97.96 | 0 | 1 |
| fileserver | A | 3 | 7.503 | 5346.250 | 2112.20 | MiB/s | 2.500 | 58.90 | 0 | 0 |
| fileserver | B | 3 | 7.276 | 5346.281 | 2095.40 | MiB/s | 2.500 | 58.80 | 3 | 0 |
| fileserver_small | A | 3 | 7.273 | 5346.109 | 1757.40 | MiB/s | 3.000 | 83.39 | 0 | 0 |
| fileserver_small | B | 3 | 7.908 | 5346.109 | 1761.40 | MiB/s | 3.000 | 83.34 | 0 | 0 |

## 每一次读取

| 工作负载 | 组 | 轮次 | 读序号 | 吞吐 | 单位 | 延迟 ms | ONFI 次数 | NAND program | NAND read |
|---|---|---:|---:|---:|---|---:|---:|---:|---:|
| sqlite | A | 1 | 1 | 35967.53 | records/s | 278.029 | 0 | 1 | 15817 |
| sqlite | A | 1 | 2 | 36098.30 | records/s | 277.021 | 0 | 0 | 15817 |
| sqlite | A | 1 | 3 | 34793.54 | records/s | 287.410 | 0 | 0 | 15817 |
| sqlite | A | 1 | 4 | 36048.89 | records/s | 277.401 | 0 | 0 | 15817 |
| sqlite | A | 1 | 5 | 33798.02 | records/s | 295.875 | 0 | 0 | 15817 |
| sqlite | A | 1 | 6 | 36297.27 | records/s | 275.503 | 0 | 0 | 15817 |
| sqlite | A | 1 | 7 | 35865.03 | records/s | 278.823 | 0 | 0 | 15817 |
| sqlite | A | 1 | 8 | 35819.54 | records/s | 279.177 | 0 | 0 | 15817 |
| sqlite | A | 1 | 9 | 36054.59 | records/s | 277.357 | 0 | 0 | 15817 |
| sqlite | A | 1 | 10 | 36040.35 | records/s | 277.467 | 0 | 0 | 15817 |
| sqlite | B | 1 | 1 | 33827.65 | records/s | 295.616 | 1 | 1 | 15817 |
| sqlite | B | 1 | 2 | 36922.90 | records/s | 270.835 | 0 | 0 | 15817 |
| sqlite | B | 1 | 3 | 36539.91 | records/s | 273.673 | 0 | 0 | 15817 |
| sqlite | B | 1 | 4 | 36657.53 | records/s | 272.795 | 0 | 0 | 15817 |
| sqlite | B | 1 | 5 | 36109.45 | records/s | 276.936 | 0 | 0 | 15817 |
| sqlite | B | 1 | 6 | 36434.55 | records/s | 274.465 | 0 | 0 | 15817 |
| sqlite | B | 1 | 7 | 33635.08 | records/s | 297.309 | 0 | 0 | 15817 |
| sqlite | B | 1 | 8 | 34345.09 | records/s | 291.162 | 0 | 0 | 15817 |
| sqlite | B | 1 | 9 | 36898.22 | records/s | 271.016 | 0 | 0 | 15817 |
| sqlite | B | 1 | 10 | 36245.04 | records/s | 275.900 | 0 | 0 | 15817 |
| fileserver | A | 1 | 1 | 2153.60 | MiB/s | 2.500 | 0 | 0 | 7606618 |
| fileserver | B | 1 | 1 | 2530.20 | MiB/s | 2.100 | 0 | 0 | 5975220 |
| fileserver_small | A | 1 | 1 | 1755.50 | MiB/s | 3.000 | 0 | 0 | 8782572 |
| fileserver_small | B | 1 | 1 | 1849.20 | MiB/s | 2.900 | 0 | 0 | 8581480 |
| sqlite | B | 2 | 1 | 33367.34 | records/s | 299.694 | 0 | 1 | 15818 |
| sqlite | B | 2 | 2 | 36890.90 | records/s | 271.070 | 0 | 0 | 15818 |
| sqlite | B | 2 | 3 | 36281.97 | records/s | 275.619 | 0 | 0 | 15818 |
| sqlite | B | 2 | 4 | 36381.62 | records/s | 274.864 | 0 | 0 | 15818 |
| sqlite | B | 2 | 5 | 34087.06 | records/s | 293.366 | 0 | 0 | 15818 |
| sqlite | B | 2 | 6 | 36239.17 | records/s | 275.944 | 0 | 0 | 15818 |
| sqlite | B | 2 | 7 | 34365.78 | records/s | 290.987 | 0 | 0 | 15818 |
| sqlite | B | 2 | 8 | 33741.24 | records/s | 296.373 | 0 | 0 | 15818 |
| sqlite | B | 2 | 9 | 36762.39 | records/s | 272.017 | 0 | 0 | 15818 |
| sqlite | B | 2 | 10 | 36109.68 | records/s | 276.934 | 0 | 0 | 15818 |
| sqlite | A | 2 | 1 | 36956.14 | records/s | 270.591 | 0 | 1 | 15817 |
| sqlite | A | 2 | 2 | 35823.75 | records/s | 279.144 | 0 | 0 | 15817 |
| sqlite | A | 2 | 3 | 36508.12 | records/s | 273.912 | 0 | 0 | 15817 |
| sqlite | A | 2 | 4 | 35313.51 | records/s | 283.178 | 0 | 0 | 15817 |
| sqlite | A | 2 | 5 | 34712.07 | records/s | 288.084 | 0 | 0 | 15817 |
| sqlite | A | 2 | 6 | 35944.52 | records/s | 278.207 | 0 | 0 | 15817 |
| sqlite | A | 2 | 7 | 33109.97 | records/s | 302.024 | 0 | 0 | 15817 |
| sqlite | A | 2 | 8 | 36230.68 | records/s | 276.009 | 0 | 0 | 15817 |
| sqlite | A | 2 | 9 | 31120.03 | records/s | 321.336 | 0 | 0 | 15817 |
| sqlite | A | 2 | 10 | 36212.15 | records/s | 276.150 | 0 | 0 | 15817 |
| fileserver | B | 2 | 1 | 2078.40 | MiB/s | 2.600 | 0 | 0 | 7356039 |
| fileserver | A | 2 | 1 | 2127.60 | MiB/s | 2.500 | 0 | 0 | 7519195 |
| fileserver_small | B | 2 | 1 | 1986.90 | MiB/s | 2.700 | 0 | 0 | 8241591 |
| fileserver_small | A | 2 | 1 | 1761.70 | MiB/s | 3.000 | 0 | 0 | 8817532 |
| sqlite | A | 3 | 1 | 36760.95 | records/s | 272.028 | 0 | 1 | 15817 |
| sqlite | A | 3 | 2 | 35092.14 | records/s | 284.964 | 0 | 0 | 15817 |
| sqlite | A | 3 | 3 | 36194.70 | records/s | 276.284 | 0 | 0 | 15817 |
| sqlite | A | 3 | 4 | 36354.95 | records/s | 275.066 | 0 | 0 | 15817 |
| sqlite | A | 3 | 5 | 34482.72 | records/s | 290.000 | 0 | 0 | 15817 |
| sqlite | A | 3 | 6 | 36593.41 | records/s | 273.273 | 0 | 0 | 15817 |
| sqlite | A | 3 | 7 | 36059.05 | records/s | 277.323 | 0 | 0 | 15817 |
| sqlite | A | 3 | 8 | 35006.70 | records/s | 285.660 | 0 | 0 | 15817 |
| sqlite | A | 3 | 9 | 36689.99 | records/s | 272.554 | 0 | 0 | 15817 |
| sqlite | A | 3 | 10 | 36116.35 | records/s | 276.883 | 0 | 0 | 15817 |
| sqlite | B | 3 | 1 | 36901.50 | records/s | 270.992 | 1 | 1 | 15817 |
| sqlite | B | 3 | 2 | 36692.58 | records/s | 272.535 | 0 | 0 | 15817 |
| sqlite | B | 3 | 3 | 36654.14 | records/s | 272.821 | 0 | 0 | 15817 |
| sqlite | B | 3 | 4 | 35148.28 | records/s | 284.509 | 0 | 0 | 15817 |
| sqlite | B | 3 | 5 | 36284.79 | records/s | 275.598 | 0 | 0 | 15817 |
| sqlite | B | 3 | 6 | 31332.28 | records/s | 319.160 | 0 | 0 | 15817 |
| sqlite | B | 3 | 7 | 36344.81 | records/s | 275.142 | 0 | 0 | 15817 |
| sqlite | B | 3 | 8 | 36255.88 | records/s | 275.817 | 0 | 0 | 15817 |
| sqlite | B | 3 | 9 | 34455.04 | records/s | 290.233 | 0 | 0 | 15817 |
| sqlite | B | 3 | 10 | 36619.47 | records/s | 273.079 | 0 | 0 | 15817 |
| fileserver | A | 3 | 1 | 2112.20 | MiB/s | 2.500 | 0 | 0 | 7465053 |
| fileserver | B | 3 | 1 | 2095.40 | MiB/s | 2.500 | 0 | 0 | 7393841 |
| fileserver_small | A | 3 | 1 | 1757.40 | MiB/s | 3.000 | 0 | 0 | 8794790 |
| fileserver_small | B | 3 | 1 | 1761.40 | MiB/s | 3.000 | 0 | 0 | 8809028 |

## 数据与验证

- [全部构造数据](../../../../../reports/apps-onfi-16g-v1/construction.csv)：含实际文件增长、报告追加字节数、计数器及写回时间。
- [全部读取数据](../../../../../reports/apps-onfi-16g-v1/reads.csv)、[独立重建](../../../../../reports/apps-onfi-16g-v1/trials.csv)、[聚合](../../../../../reports/apps-onfi-16g-v1/aggregate.csv)、[A/B 差值](../../../../../reports/apps-onfi-16g-v1/comparisons.csv)。
- [源码与运行配置](../../../../../reports/apps-onfi-16g-v1/source_manifest.json)。
- [原始日志和计数器归档](../../../../../reports/apps-onfi-16g-v1/raw-results.tar.gz)，逐文件校验值见 [raw_inventory.csv](../../../../../reports/apps-onfi-16g-v1/raw_inventory.csv)。
- SQLite 所有字段、主键顺序和 integrity_check 通过；Filebench 读取前后大小及 SHA256 一致。
- 应用无错误退出、无被拒绝的 NVMe I/O 或主机 FAST 提示；VM 参数已恢复。
- 标准差反映独立构造的离散程度，不是显著性检验；Filebench 并发轨迹未逐请求锁定。
- SQLite filefrag 记录为 10,000–10,001 个 extent；论文报告 DoF 5,005，不能声称文件布局完全一致。
- [本机硬件和已加载模块信息](../../../../../reports/apps-onfi-16g-v1/environment.json)；CPU 频率未固定。
