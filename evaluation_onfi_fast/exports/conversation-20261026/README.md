# 对话与 Markdown 报告归档

报告源码基线：`bcfebf1480ae70eeee389cb095820b7af1772a4b`。对话截止 2026-10-26 05:22:16（北京时间）。

- [按时间顺序查看对话](CONVERSATION.zh-CN.md)：包含全部可导出的用户消息和助手可见答复/进度。
- [机器可读对话](conversation.jsonl)：逐条角色、时间、阶段和正文。
- [报告文件校验清单](report_inventory.csv)：源文件和导出快照的 SHA256。

密码等凭据已脱敏。系统/开发者消息、内部推理、工具原始日志以及 PDF 附件不在本导出中。
报告快照保留该提交下全部 evaluation_onfi_fast Markdown 文档；其中的相对文件链接指向仓库原文件，
便于访问已经纳入版本控制的 CSV、图片和原始实验日志压缩包，不重复复制这些数据。
链接转换会改变快照文件的 SHA256，因此清单同时保存源文件和快照校验值。

## 主要报告

| 内容 | 快照 |
|---|---|
| 中文总结果 | [RESULTS.zh-CN.md](report-snapshot/RESULTS.zh-CN.md) |
| 全部实验总表 | [ALL_RESULTS.zh-CN.md](report-snapshot/reports/all-experiments/ALL_RESULTS.zh-CN.md) |
| fio：ONFI / FAST 四组，96 项 | [SUMMARY.md](report-snapshot/reports/fio-fast-16g-v1/SUMMARY.md) |
| fio：ONFI 开关，48 项 | [SUMMARY.md](report-snapshot/reports/fio-onfi-16g-v1/SUMMARY.md) |
| ONFI 冲突诊断 | [SUMMARY.md](report-snapshot/reports/onfi-positive-16g-v3/SUMMARY.md) |
| SQLite / Filebench | [SUMMARY.md](report-snapshot/reports/apps-onfi-16g-v1/SUMMARY.md) |
| FAST 设备级方法复现 | [SUMMARY.md](report-snapshot/reports/main-16g-aio-v1/SUMMARY.md) |

## 全部 Markdown 快照

- [evaluation_onfi_fast/APPLICATIONS.zh-CN.md](report-snapshot/APPLICATIONS.zh-CN.md)
- [evaluation_onfi_fast/FAST_FIO.zh-CN.md](report-snapshot/FAST_FIO.zh-CN.md)
- [evaluation_onfi_fast/FIO.zh-CN.md](report-snapshot/FIO.zh-CN.md)
- [evaluation_onfi_fast/README.md](report-snapshot/README.md)
- [evaluation_onfi_fast/RESULTS.zh-CN.md](report-snapshot/RESULTS.zh-CN.md)
- [evaluation_onfi_fast/reports/all-experiments/ALL_RESULTS.zh-CN.md](report-snapshot/reports/all-experiments/ALL_RESULTS.zh-CN.md)
- [evaluation_onfi_fast/reports/apps-development/STATUS.md](report-snapshot/reports/apps-development/STATUS.md)
- [evaluation_onfi_fast/reports/apps-onfi-16g-v1/SUMMARY.md](report-snapshot/reports/apps-onfi-16g-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/apps-smoke-v3/SUMMARY.md](report-snapshot/reports/apps-smoke-v3/SUMMARY.md)
- [evaluation_onfi_fast/reports/fio-fast-16g-v1/SUMMARY.md](report-snapshot/reports/fio-fast-16g-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/fio-fast-infer-smoke-v1/SUMMARY.md](report-snapshot/reports/fio-fast-infer-smoke-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/fio-fast-switch-smoke-v1/SUMMARY.md](report-snapshot/reports/fio-fast-switch-smoke-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/fio-onfi-16g-v1/SUMMARY.md](report-snapshot/reports/fio-onfi-16g-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/fio-onfi-smoke-v1/SUMMARY.md](report-snapshot/reports/fio-onfi-smoke-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/main-16g-aio-v1/SUMMARY.md](report-snapshot/reports/main-16g-aio-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/main-16g-v1/SUMMARY.md](report-snapshot/reports/main-16g-v1/SUMMARY.md)
- [evaluation_onfi_fast/reports/onfi-positive-16g-v3/SUMMARY.md](report-snapshot/reports/onfi-positive-16g-v3/SUMMARY.md)
