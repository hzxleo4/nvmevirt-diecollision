/* SPDX-License-Identifier: GPL-2.0-only */
/* Minimal kernel/SSD boundary for exercising the actual fast24_ftl.c allocator.
 * The timing unit itself is tested separately; this harness is not a benchmark.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include "../onfi_model.h"
typedef unsigned long long u64;
typedef unsigned int u32;
typedef unsigned char u8;
#define GFP_KERNEL 0
#define U32_MAX UINT32_MAX
#define NVMEV_ASSERT(x) assert(x)
#define NVMEV_INFO(...) ((void)0)
#define module_param(a,b,c)
#define MODULE_PARM_DESC(a,b)
#define max(a,b) ((a) > (b) ? (a) : (b))
#define round_down(a,b) ((a) / (b) * (b))
#define array_size(a,b) ((a) * (b))
#define kzalloc(n,f) calloc(1,n)
#define kcalloc(n,s,f) calloc(n,s)
#define vmalloc(n) malloc(n)
#define vfree(p) free(p)
#define kfree(p) free(p)
#define le64_to_cpu(v) (v)
#define le16_to_cpu(v) (v)
#define spin_lock_irqsave(lock,flags) ((flags) = 0)
#define spin_unlock_irqrestore(lock,flags) ((void)(flags))
#define NVME_CSI_NVM 0
#define NVME_SC_SUCCESS 0
#define NVME_SC_INVALID_FIELD 2
#define NVME_SC_INTERNAL 6
#define NVME_SC_LBA_RANGE 128
#define NVME_SC_INVALID_OPCODE 1
#define NVME_RW_FUA (1U << 14)
#define LBA_SIZE 512
#define INVALID_LPN (~0ULL)
#define UNMAPPED_PPA (~0ULL)
enum { NAND_READ, NAND_WRITE, NAND_ERASE, NAND_NOP };
enum { USER_IO, GC_IO };
enum { PG_FREE, PG_INVALID, PG_VALID };
enum { nvme_cmd_flush, nvme_cmd_write, nvme_cmd_read };
struct ppa {
	union {
		struct { u64 pg:16, blk:16, pl:8, lun:8, ch:8, rsv:8; } g;
		struct { u64 :16, blk_in_ssd:40, rsv:8; } h;
		u64 ppa;
	};
};
struct nand_page { int status; };
struct nand_block { struct nand_page *pg; int vpc, ipc, erase_cnt; };
struct buffer { size_t size, remaining; };
struct ssdparams {
	u32 nchs, blks_per_pl, pgs_per_blk, pgs_per_flashpg, pgsz, secs_per_pg;
	u64 tt_luns, tt_pgs, write_buffer_size;
	u32 fw_4kb_rd_lat, fw_rd_lat;
};
struct ssd_channel { struct onfi_target onfi; int timing_lock; };
struct ssd {
	struct ssdparams sp;
	struct buffer *write_buffer;
	struct ssd_channel *ch;
	struct nand_block *blocks;
	bool onfi_collision;
	u64 clock;
};
struct nand_cmd { struct ppa *ppa; int cmd, type; u64 stime; u32 xfer_size; bool interleave_pci_dma; };
struct nvme_rw_command {
	u8 opcode;
	u64 slba, rsvd2;
	unsigned short length, control;
};
struct nvme_command {
	union { struct nvme_rw_command rw; struct { u8 opcode; } common; };
};
struct nvmev_request { struct nvme_command *cmd; int sq_id; u64 nsecs_start; };
struct nvmev_result { u32 status; u64 nsecs_target; };
struct nvmev_ns {
	u32 id, csi, nr_parts;
	u64 size;
	void *ftls, *mapped;
	bool (*proc_io_cmd)(struct nvmev_ns *, struct nvmev_request *, struct nvmev_result *);
};
struct seq_file { int unused; };
#define seq_printf(m, ...) do { if (m) printf(__VA_ARGS__); } while (0)
static void ssd_init_params(struct ssdparams *s, u64 size, u32 parts)
{
	(void)size; (void)parts;
	*s = (struct ssdparams){ .nchs=2, .blks_per_pl=8, .pgs_per_blk=32,
		.pgs_per_flashpg=8, .pgsz=4096, .secs_per_pg=8, .tt_luns=4,
		.tt_pgs=1024, .write_buffer_size=4*1024*1024 };
}
static void ssd_init(struct ssd *s, struct ssdparams *p, u32 cpu)
{
	u32 i;
	(void)cpu;
	s->sp = *p;
	s->ch = calloc(p->nchs, sizeof(*s->ch));
	s->blocks = calloc(p->tt_luns * p->blks_per_pl, sizeof(*s->blocks));
	for (i=0; i<p->tt_luns * p->blks_per_pl; i++)
		s->blocks[i].pg = calloc(p->pgs_per_blk, sizeof(struct nand_page));
	s->write_buffer = malloc(sizeof(*s->write_buffer));
	*s->write_buffer = (struct buffer){p->write_buffer_size,p->write_buffer_size};
}
static struct nand_block *get_blk(struct ssd *s, struct ppa *p)
{
	assert(p->g.pg < s->sp.pgs_per_blk && p->g.blk < s->sp.blks_per_pl);
	return &s->blocks[(p->g.lun * s->sp.nchs + p->g.ch) * s->sp.blks_per_pl + p->g.blk];
}
static struct nand_page *get_pg(struct ssd *s, struct ppa *p)
{ return &get_blk(s,p)->pg[p->g.pg]; }
static void ssd_remove(struct ssd *s)
{
	u32 i;
	for(i=0;i<s->sp.tt_luns*s->sp.blks_per_pl;i++) free(s->blocks[i].pg);
	free(s->blocks); free(s->ch); free(s->write_buffer);
}
static u64 ssd_advance_nand(struct ssd *s, struct nand_cmd *c)
{
	(void)c;
	return ++s->clock;
}
static u64 ssd_next_idle_time(struct ssd *s) { return s->clock; }
static u64 ssd_advance_write_buffer(struct ssd *s,u64 start,u32 bytes)
{ (void)s; (void)bytes; return start; }
static u32 buffer_allocate(struct buffer *b, u32 bytes)
{ if (b->remaining<bytes) return 0; b->remaining-=bytes; return bytes; }
static bool buffer_release(struct buffer *b, u32 bytes)
{ b->remaining+=bytes; assert(b->remaining<=b->size); return true; }
static void schedule_internal_operation(int sq,u64 end,struct buffer *b,u32 bytes)
{ (void)sq; (void)end; buffer_release(b,bytes); }
