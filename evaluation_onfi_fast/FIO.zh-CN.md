# fio：16 GiB ONFI 常规随机读写

这是独立的 ONFI 合成负载实验，不属于 FAST '24 的应用结果。
沿用相邻 `nvmevirt-clssd/benchmarks/nvmev_fio_matrix.sh` 的 libaio、direct I/O、
单 job 和固定 I/O 量测试思路；这里使用同一个 FAST24 FTL，仅切换 ONFI。
不选择 die，不构造指定 die 间的交替访问，也不发送 FAST 文件提示。
默认 `--groups A B` 保留这个实验；[FAST 覆盖适配的四组实验](FAST_FIO.zh-CN.md)
使用 `--groups A B C D --infer-overwrite`，单列报告，不能与默认实验混淆。

| 请求大小 | QD | 读比例 |
|---|---:|---|
| 4 KiB | 32 | 100%、70%、50%、30%、0% |
| 4 KiB | 1 | 50% |
| 32 KiB | 32、1 | 50% |

每种配置进行 ONFI 关/开两组、三轮独立重建，共 48 个正式用例。
主机 CPU 3，模拟器 CPU 7–10。每个用例都创建新的 16 GiB NVMeVirt，
仅对新发现且型号为 `NVMeVirt_FAST24`、无挂载/分区/holder 的 namespace 写入。
不创建文件系统、不修改主机内核或 VM 参数。

1. 顺序填充 2 GiB 工作集，显式 `nvme flush`，使所有读地址都有数据。
2. fio 在该范围内做均匀随机访问，完成固定 2 GiB 总 I/O，非 time_based。
3. 再显式 flush；末尾 flush 的计数单列，不混入 fio 内部测量窗口。
4. 完整读取 2 GiB 检查固定数据模式，然后卸载模块、检查内核错误。

使用本机 fio 3.28，libaio、direct=1、numjobs=1、tausworthe64、norandommap=1。
同轮同配置 A/B 使用相同 randseed，randrepeat/allrandrepeat 开启，并核对实际
完成的读/写字节数。并发完成顺序可能不同，不能据种子声称时序逐请求完全一致。
写入使用固定模式；验证在测量后进行，不向计时路径增加读数据校验开销。
固定模式校验可发现内容错误，但不能发现两个内容完全相同的 LBA 之间的别名。

这轮选择有限 I/O 量来隔离 ONFI；若发生 GC，runner 拒绝作为本组正式结果。
它不是满盘、老化或持续 GC 的稳态测试。纯读/纯写作为对照，混合访问检查
NAND read 和 program 的自然重叠。QD1 也保留实际计数，不预设一定为零。

统计包括总 IOPS、总吞吐、读写各自平均延迟与 P99 completion latency、
ONFI 等待次数/时间、NAND 操作数、GC 及最终 flush。
吞吐按 fio 的共同 job_runtime 和读写总字节计算；读写分开报告 P99，
不把两个 P99 平均成“总 P99”。三轮平均 P99 也不是合并请求后的 P99。
ONFI 累计等待可能在不同操作/通道上重叠，不能直接当作应用墙钟损失。
当前 FTL 的非 FUA 写在进入设备写缓冲后返回，因此写延迟不是 NAND program
完成延迟；读变慢时写请求的到达节奏也会变化，不能要求读写两类延迟都上升。
计数窗口覆盖整个 fio 进程，吞吐和延迟取自 fio 内部 job 计时。即使已经等待
udev 和设备计数稳定，纯写进程窗口仍可能记录少量额外 NAND read；保留原始
计数，不将整个窗口宣称为严格没有其他读取。它们的来源没有逐请求跟踪定位。

```bash
python3 evaluation_onfi_fast/run_fio.py --plan-only
sudo python3 evaluation_onfi_fast/run_fio.py --smoke --out evaluation_onfi_fast/results/fio-onfi-smoke
sudo python3 evaluation_onfi_fast/run_fio.py --out evaluation_onfi_fast/results/fio-onfi-16g-v1
python3 evaluation_onfi_fast/summarize_fio.py evaluation_onfi_fast/results/fio-onfi-16g-v1 --output evaluation_onfi_fast/reports/fio-onfi-16g-v1
```

冒烟把工作集缩为 16 MiB、I/O 缩为 32 MiB，仅用于功能验证。
正式运行保存源代码 SHA256、fio 命令/JSON、阶段计数、每秒采样和数据验证结果。
