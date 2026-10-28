/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NVMEV_FAST24_FTL_H
#define NVMEV_FAST24_FTL_H
struct seq_file;
struct nvmev_ns;
void fast24_debug(struct seq_file *m, struct nvmev_ns *ns);
void fast24_trace(struct seq_file *m, struct nvmev_ns *ns);
#endif
