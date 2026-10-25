# SQLite / Filebench 的 ONFI 应用实验

本实验仅比较 A（ONFI 关）与 B（ONFI 开），两者 `fast_placement=0`。
使用现有 Linux 主机、相同 FAST24 FTL 和 16 GiB 物理预留空间；逻辑容量以
每个用例的 `device.json` 为准。这是 FAST '24 应用负载的 ONFI A/B 实验，
不是带 FAST 主机提示的应用级复现，也不是完整 CLSSD 调度架构的比较。

协议来源：[FAST '24 §5.2](https://www.usenix.org/conference/fast24/presentation/jun)，
[作者工作负载代码](https://github.com/yuhun-Jun/fast24_ae/tree/89ba3a9c5e7e5cfbb9929d59fb6e3389a9119ecd)。
Filebench 固定为官方 1.5-alpha3 / `1263cb180c48a63253345a12e2b842cd9f85fa26`，
SQLite 链接本机库，版本写入结果。脚本自行实现相应参数和操作流程。

## 负载与测量

| 项目 | SQLite | Filebench fileserver | Filebench fileserver_small |
|---|---|---|---|
| 初始数据 | 倒序插入 10,000 条，每条约 16 KiB | 10,000 个 128 KiB 文件 | 同左 |
| 构造 | 每次 INSERT 后追加 dummy 100 KiB 并 fdatasync | 10 线程随机选文件、追加 32 KiB、关闭 | 追加 16 KiB |
| 写入设置 | journal_mode=OFF、synchronous=ON、逐条自动提交 | buffered append；无逐次 fsync | 同左 |
| 结束条件 | 10,000 条全部完成 | 累计追加操作达到 4 GiB | 同左 |
| 写后处理 | 关闭数据库并 syncfs | syncfs 等待文件系统写回完成 | 同左 |
| 读取 | SELECT * FROM DB1，冷读 10 次 | 10 线程 direct I/O 读随机文件，每次读完整文件，持续 60 秒 | 同左 |
| 重复 | 每个开关状态独立重建 3 次 | 同左 | 同左 |
| 验证 | 逐条检查 ID/所有字段及 integrity_check | 10,000 个文件前后大小与 SHA256 一致 | 同左 |

每个用例重载模块、重新创建文件系统。按重复轮次交换 A/B 先后顺序。
SQLite 同一轮 A/B 使用同一个确定性数据种子；manifest 中的 seed 只用于
SQLite 数据内容。Filebench 沿用上游随机源，线程调度和分配轨迹不能保证
完全相同，需结合重复间离散程度与设备计数器解释结果。
SQLite 每次 SELECT 前执行两轮 sync、drop_caches、等待 5 秒；Filebench 读前
清缓存并等待 5 秒。SHA256 校验不计入测量，校验后的缓存也在读前清除。

程序绑到 CPU 0–5，模拟器绑到 CPU 7–10。使用 ext4、4 KiB 块、
`nodelalloc,noatime`，关闭 reserved_clusters，设置 `mb_stream_req=4200000000`。
独立的 512 MiB ext4 journal 放在临时 tmpfs loop 设备上，使日志不争用被测
模拟闪存；这与作者使用另一块存储设备的日志布局不同。
作者采用的 dirty_ratio/background_ratio=50、writeback_centisecs=0、
expire_centisecs=60000 在实验结束后恢复原值。

## 明确的容量适配和实现修正

论文 Filebench 追加 60 秒，作者 artifact 配置为 30 秒。本机冒烟测得 2 秒
可以提交约 5 GiB buffered append，直接追加 60 秒无法保证容纳在 16 GiB 中。
因此正式实验用 `finishonbytes` 限定 4 GiB 追加操作，得到约 5.22 GiB 数据集，
保留论文的 10,000 文件、10 线程、32/16 KiB 追加和写后读协议。
这个数据集小于论文报告的 11 GB；不能将结果称为完整复现论文的
60 秒追加实验，也不能外推到满盘或持续 GC 的情况。

`finishonbytes` 检查共享计数器，多线程结束时存在少量超量操作。
Filebench `appendfile` 本身使用 lseek + write，并非原子 O_APPEND，实际文件
增长也不一定等于操作字节数；两种量均记录，偏差超过预算 1% 则拒绝正式结果。
`finishonbytes` 的检查有额外开销，且 Filebench 停止计时有秒级粒度，因此
短暂 buffered append 的 MB/s 不宜作为设备持续写带宽。
报告同时提供包含初始文件创建、追加、进程开销和末尾写回的构造总时间。

Filebench 1.5-alpha3 的 `reuse` 在预分配时会截短超出声明大小的文件。
读取配置额外指定 `trusttree` 保留追加后的文件，使用前后哈希校验来验证。
不修改 Filebench 二进制或主机内核。

## 归因和结果口径

分别保存构造/读取前后的 ONFI wait_events、wait_ns、NAND reads/programs 和 GC。
Filebench 构造计数覆盖创建、追加与最后写回；Filebench 自报追加吞吐仅覆盖
计时追加循环，两者不是同一时间窗口。SQL 构造时间包含全部插入和 dummy 写入。
ONFI wait_ns 是模拟器累计的排队等待，跨操作/通道可能重叠，不能直接当成
应用墙钟损失或把它除以运行时间称为性能降幅。

应用按论文先写后读。如果读阶段没有 NAND program，ONFI 的 program-vs-read
限制就没有触发条件。即便两组吞吐略有差异，也不能单凭差值归因为 ONFI。
这个实验不增加两个 die 的人为交替，也不额外混入读写线程。

`syncfs` 保证主机文件系统的写回，不等同于主动发出 NVMe FLUSH。当前控制器
报告 VWC=0；FTL 尚未填满的 32 KiB 页可能留到首次读时补齐并 program
（`fast24_ftl.c:fast_read`）。因此不能预先假定所有读取窗口的 program 数为零。
报告同时检查主机 WRITE 增量、NAND program 和 GC，保留首遍读取的真实计数。

## 运行

```bash
bash evaluation_onfi_fast/prepare_filebench.sh
python3 evaluation_onfi_fast/run_applications.py --plan-only
sudo python3 evaluation_onfi_fast/run_applications.py --smoke --out evaluation_onfi_fast/results/apps-smoke
sudo python3 evaluation_onfi_fast/run_applications.py --out evaluation_onfi_fast/results/apps-onfi-16g-v1
python3 evaluation_onfi_fast/summarize_applications.py evaluation_onfi_fast/results/apps-onfi-16g-v1 --output evaluation_onfi_fast/reports/apps-onfi-16g-v1
```

必须已有 `memmap=16G$8G` 预留内存。runner 拒绝已有 nvmev 模块，只格式化
刚创建且型号核对为 `NVMeVirt_FAST24` 的 namespace；外部日志也核对 loop
backing file。失败不纳入正式汇总，退出时卸载文件系统、模块并恢复系统参数。
`--smoke` 仅用 100 条/100 文件、32 MiB 追加、2 秒读，不属于正式性能结果。
