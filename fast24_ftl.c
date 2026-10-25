// SPDX-License-Identifier: GPL-2.0-only
/* FAST24 page-to-die placement on current NVMeVirt.
 * Policy follows Jun et al.; allocator, buffering and GC are shared by ON/OFF.
 * NVMeVirt's single command dispatcher owns all mapping/allocator state.
 */
#ifdef NVMEV_FAST24_TEST
#include "tests/ftl_shim.h"
#else
#include <linux/module.h>
#include <linux/vmalloc.h>
#include <linux/seq_file.h>
#include "nvmev.h"
#include "conv_ftl.h"
#include "fast24_ftl.h"
#endif
#include "fast24_placement.h"

static bool fast_placement;
module_param(fast_placement, bool, 0444);
MODULE_PARM_DESC(fast_placement, "FAST24 append/overwrite placement; reload to switch");

/* Raw-device fio overwrites an already mapped LBA. This optional adapter
 * supplies only that fact; it cannot infer file adjacency or append hints.
 * Keep the original explicit-hint behavior as the default.
 */
static bool fast_infer_overwrite;
module_param(fast_infer_overwrite, bool, 0444);
MODULE_PARM_DESC(fast_infer_overwrite, "Infer raw-LBA overwrites for FAST24; default off, reload to switch");

enum block_state { BLOCK_FREE, BLOCK_USER, BLOCK_GC, BLOCK_CLOSED };

struct fast_cursor {
	u32 block, page;
	u32 pending, buffered_bytes;
	u64 ready;
};

struct fast_die {
	struct fast_cursor user, gc;
	u8 *state;
	u32 free_blocks, next_free;
	u64 reads, programs, erases, gc_pages, gc_count, live_pages;
};

struct fast_ftl {
	struct ssd ssd;
	struct ppa *map;
	u64 *rmap;
	struct fast_die *dies;
	u32 next_die;
	u64 writes, append_hints, overwrite_hints, applied_hints, missing_hints;
	u64 rejected, read_pages;
	u64 inferred_candidates, inferred_applied, inferred_changed;
	bool placement, infer_overwrite;
};

static u32 die_id(struct fast_ftl *f, struct ppa p)
{
	return p.g.lun * f->ssd.sp.nchs + p.g.ch;
}

static struct ppa make_ppa(struct fast_ftl *f, u32 die, u32 block, u32 page)
{
	struct ppa p = { .ppa = 0 };
	p.g.ch = die % f->ssd.sp.nchs;
	p.g.lun = die / f->ssd.sp.nchs;
	p.g.blk = block;
	p.g.pg = page;
	return p;
}

static u64 fast_page_index(struct fast_ftl *f, struct ppa p)
{
	return ((u64)die_id(f, p) * f->ssd.sp.blks_per_pl + p.g.blk) *
		f->ssd.sp.pgs_per_blk + p.g.pg;
}

static struct nand_block *block_at(struct fast_ftl *f, u32 die, u32 block)
{
	struct ppa p = make_ppa(f, die, block, 0);
	return get_blk(&f->ssd, &p);
}

static u64 flash_cmd(struct fast_ftl *f, struct ppa p, int cmd, int type,
		     u64 start, u32 bytes, bool pci)
{
	struct nand_cmd c = { .ppa = &p, .cmd = cmd, .type = type,
		.stime = start, .xfer_size = bytes, .interleave_pci_dma = pci };
	struct fast_die *d = &f->dies[die_id(f, p)];
	if (cmd == NAND_READ)
		d->reads++;
	else if (cmd == NAND_WRITE)
		d->programs++;
	else if (cmd == NAND_ERASE)
		d->erases++;
	return ssd_advance_nand(&f->ssd, &c);
}

static void invalidate(struct fast_ftl *f, struct ppa p)
{
	struct nand_block *b = get_blk(&f->ssd, &p);
	struct nand_page *pg = get_pg(&f->ssd, &p);
	NVMEV_ASSERT(pg->status == PG_VALID && b->vpc > 0);
	pg->status = PG_INVALID;
	b->vpc--;
	b->ipc++;
	f->dies[die_id(f, p)].live_pages--;
	f->rmap[fast_page_index(f, p)] = INVALID_LPN;
}

static void map_page(struct fast_ftl *f, u64 lpn, struct ppa p)
{
	struct nand_block *b = get_blk(&f->ssd, &p);
	NVMEV_ASSERT(get_pg(&f->ssd, &p)->status == PG_FREE);
	get_pg(&f->ssd, &p)->status = PG_VALID;
	b->vpc++;
	f->dies[die_id(f, p)].live_pages++;
	f->map[lpn] = p;
	f->rmap[fast_page_index(f, p)] = lpn;
}

/* Program a partially/full populated flash page. Partial flush pads unused
 * mapping slots; they cannot be subsequently programmed a second time.
 * Buffer space is released only at the modeled program completion.
 */
static u64 close_flash_page(struct fast_ftl *f, u32 die, bool gc, u64 start, int sq)
{
	struct fast_die *d = &f->dies[die];
	struct fast_cursor *c = gc ? &d->gc : &d->user;
	struct ssdparams *s = &f->ssd.sp;
	u64 end;
	u32 page, pad;
	struct ppa p;
	if (!c->pending)
		return start;
	page = c->page - c->pending;
	p = make_ppa(f, die, c->block, page);
	end = flash_cmd(f, p, NAND_WRITE, gc ? GC_IO : USER_IO,
		max(start, c->ready), s->pgs_per_flashpg * s->pgsz, false);
	pad = s->pgs_per_flashpg - c->pending;
	while (pad--) {
		p.g.pg = c->page++;
		NVMEV_ASSERT(get_pg(&f->ssd, &p)->status == PG_FREE);
		get_pg(&f->ssd, &p)->status = PG_INVALID;
		get_blk(&f->ssd, &p)->ipc++;
	}
	if (c->buffered_bytes)
		schedule_internal_operation(sq, end, f->ssd.write_buffer, c->buffered_bytes);
	c->pending = c->buffered_bytes = 0;
	c->ready = 0;
	if (c->page == s->pgs_per_blk) {
		d->state[c->block] = BLOCK_CLOSED;
		c->block = U32_MAX;
		c->page = 0;
	}
	return end;
}

static bool open_block(struct fast_ftl *f, u32 die, bool gc)
{
	struct fast_die *d = &f->dies[die];
	struct fast_cursor *c = gc ? &d->gc : &d->user;
	u32 n = f->ssd.sp.blks_per_pl, i;
	if (c->block != U32_MAX)
		return true;
	for (i = 0; i < n; i++) {
		u32 b = (d->next_free + i) % n;
		if (d->state[b] != BLOCK_FREE)
			continue;
		d->state[b] = gc ? BLOCK_GC : BLOCK_USER;
		d->free_blocks--;
		d->next_free = (b + 1) % n;
		c->block = b;
		c->page = 0;
		return true;
	}
	return false;
}

/* Per-die GC keeps the placement invariant and a relocation reserve.
 * It is deliberately identical in all four experiment groups.
 */
static bool collect_die(struct fast_ftl *f, u32 die, u64 *time, int sq)
{
	struct fast_die *d = &f->dies[die];
	struct ssdparams *s = &f->ssd.sp;
	u32 victim = U32_MAX, best = s->pgs_per_blk, b, pg;
	u64 end = *time;
	for (b = 0; b < s->blks_per_pl; b++) {
		struct nand_block *blk = block_at(f, die, b);
		if (d->state[b] == BLOCK_CLOSED && (u32)blk->vpc < best) {
			victim = b;
			best = blk->vpc;
		}
	}
	if (victim == U32_MAX)
		return false;
	for (pg = 0; pg < s->pgs_per_blk; pg += s->pgs_per_flashpg) {
		u32 k, valid = 0;
		struct ppa old = make_ppa(f, die, victim, pg);
		u64 read_end;
		for (k = 0; k < s->pgs_per_flashpg; k++) {
			old.g.pg = pg + k;
			valid += get_pg(&f->ssd, &old)->status == PG_VALID;
		}
		if (!valid)
			continue;
		old.g.pg = pg;
		read_end = flash_cmd(f, old, NAND_READ, GC_IO, end, valid * s->pgsz, false);
		for (k = 0; k < s->pgs_per_flashpg; k++) {
			struct ppa dest;
			u64 lpn;
			old.g.pg = pg + k;
			if (get_pg(&f->ssd, &old)->status != PG_VALID)
				continue;
			if (!open_block(f, die, true))
				return false;
			lpn = f->rmap[fast_page_index(f, old)];
			dest = make_ppa(f, die, d->gc.block, d->gc.page++);
			invalidate(f, old);
			map_page(f, lpn, dest);
			d->gc.pending++;
			d->gc.ready = max(d->gc.ready, read_end);
			d->gc_pages++;
			if (d->gc.pending == s->pgs_per_flashpg)
				end = max(end, close_flash_page(f, die, true, read_end, sq));
		}
	}
	end = max(end, close_flash_page(f, die, true, end, sq));
	{
		struct ppa p = make_ppa(f, die, victim, 0);
		struct nand_block *blk = get_blk(&f->ssd, &p);
		end = flash_cmd(f, p, NAND_ERASE, GC_IO, end, 0, false);
		for (pg = 0; pg < s->pgs_per_blk; pg++)
			blk->pg[pg].status = PG_FREE;
		blk->vpc = blk->ipc = 0;
		blk->erase_cnt++;
	}
	d->state[victim] = BLOCK_FREE;
	d->free_blocks++;
	d->gc_count++;
	*time = end;
	return true;
}

static bool ensure_space(struct fast_ftl *f, u32 die, u64 *time, int sq)
{
	struct fast_die *d = &f->dies[die];
	if (d->user.block != U32_MAX)
		return true;
	if (d->free_blocks <= 2)
		collect_die(f, die, time, sq);
	/* Preserve one whole block for relocation, even under skewed writes. */
	return d->free_blocks > 1 && open_block(f, die, false);
}

static u64 flush_all(struct fast_ftl *f, u64 start, int sq)
{
	u32 die;
	u64 end = start;
	for (die = 0; die < f->ssd.sp.tt_luns; die++) {
		end = max(end, close_flash_page(f, die, false, start, sq));
		end = max(end, close_flash_page(f, die, true, start, sq));
	}
	return max(end, ssd_next_idle_time(&f->ssd));
}

static bool fast_write(struct nvmev_ns *ns, struct nvmev_request *req,
		       struct nvmev_result *ret)
{
	struct fast_ftl *f = ns->ftls;
	struct ssdparams *s = &f->ssd.sp;
	struct nvme_command *cmd = req->cmd;
	u64 slba = le64_to_cpu(cmd->rw.slba);
	u32 sectors = le16_to_cpu(cmd->rw.length) + 1;
	u32 bytes = sectors * LBA_SIZE;
	u64 first = slba / s->secs_per_pg, last = (slba + sectors - 1) / s->secs_per_pg;
	u64 prev = le64_to_cpu(cmd->rw.rsvd2) / s->secs_per_pg;
	u32 control = le16_to_cpu(cmd->rw.control);
	u64 lpn, ingress, end;
	int previous_die = -1;
	/* The experiment profile supports 4 KiB aligned host I/O. */
	if (slba % s->secs_per_pg || sectors % s->secs_per_pg ||
	    bytes > s->write_buffer_size ||
	    (control & (FAST24_APPEND | FAST24_OVERWRITE)) ==
		(FAST24_APPEND | FAST24_OVERWRITE)) {
		ret->status = NVME_SC_INVALID_FIELD;
		f->rejected++;
		return true;
	}
	if (buffer_allocate(f->ssd.write_buffer, bytes) < bytes)
		return false;
	ingress = ssd_advance_write_buffer(&f->ssd, req->nsecs_start, bytes);
	end = ingress;
	f->writes++;
	f->append_hints += !!(control & FAST24_APPEND);
	f->overwrite_hints += !!(control & FAST24_OVERWRITE);
	if ((control & FAST24_APPEND) && prev < s->tt_pgs &&
	    f->map[prev].ppa != UNMAPPED_PPA)
		previous_die = die_id(f, f->map[prev]);
	for (lpn = first; lpn <= last; lpn++) {
		struct ppa old = f->map[lpn], p;
		int old_die = old.ppa == UNMAPPED_PPA ? -1 : (int)die_id(f, old);
		bool inferred = f->infer_overwrite && old_die >= 0 &&
			!(control & (FAST24_APPEND | FAST24_OVERWRITE));
		u32 placement_control = inferred ? control | FAST24_OVERWRITE : control;
		u32 die = fast24_select_die(f->placement, placement_control, f->next_die,
			old_die, previous_die, s->tt_luns, lpn == first);
		struct fast_die *d = &f->dies[die];
		if (!ensure_space(f, die, &end, req->sq_id)) {
			buffer_release(f->ssd.write_buffer, (last - lpn + 1) * s->pgsz);
			ret->status = NVME_SC_INTERNAL;
			ret->nsecs_target = end;
			f->rejected++;
			return true;
		}
		if (inferred) {
			f->inferred_candidates++;
			if (f->placement) {
				f->inferred_applied++;
				f->inferred_changed += die != f->next_die;
			}
		}
		if (f->placement && ((control & FAST24_OVERWRITE && old_die >= 0) ||
		    (lpn == first && control & FAST24_APPEND && previous_die >= 0)))
			f->applied_hints++;
		else if (f->placement && (control & (FAST24_APPEND | FAST24_OVERWRITE)))
			f->missing_hints += lpn == first;
		/* GC may have relocated this LPN while reserving space. */
		old = f->map[lpn];
		if (old.ppa != UNMAPPED_PPA)
			invalidate(f, old);
		p = make_ppa(f, die, d->user.block, d->user.page++);
		map_page(f, lpn, p);
		d->user.pending++;
		d->user.buffered_bytes += s->pgsz;
		d->user.ready = max(d->user.ready, ingress);
		f->next_die = die;
		if (d->user.pending == s->pgs_per_flashpg) {
			end = max(end, close_flash_page(f, die, false, ingress, req->sq_id));
			f->next_die = (die + 1) % s->tt_luns;
		}
	}
	if (control & NVME_RW_FUA)
		end = flush_all(f, end, req->sq_id);
	ret->nsecs_target = control & NVME_RW_FUA ? end : ingress;
	ret->status = NVME_SC_SUCCESS;
	return true;
}

static bool same_flash(struct fast_ftl *f, struct ppa a, struct ppa b)
{
	return a.h.blk_in_ssd == b.h.blk_in_ssd &&
		a.g.pg / f->ssd.sp.pgs_per_flashpg == b.g.pg / f->ssd.sp.pgs_per_flashpg;
}

static void fast_read(struct nvmev_ns *ns, struct nvmev_request *req,
		      struct nvmev_result *ret)
{
	struct fast_ftl *f = ns->ftls;
	struct ssdparams *s = &f->ssd.sp;
	u64 slba = le64_to_cpu(req->cmd->rw.slba);
	u32 sectors = le16_to_cpu(req->cmd->rw.length) + 1;
	u64 first = slba / s->secs_per_pg, last = (slba + sectors - 1) / s->secs_per_pg;
	u64 start = req->nsecs_start + (sectors * LBA_SIZE <= 4096 ?
		s->fw_4kb_rd_lat : s->fw_rd_lat), end = start, lpn;
	struct ppa prev = { .ppa = UNMAPPED_PPA };
	u32 bytes = 0;
	for (lpn = first; lpn <= last + 1; lpn++) {
		struct ppa p = { .ppa = UNMAPPED_PPA };
		if (lpn <= last)
			p = f->map[lpn];
		if (bytes && (p.ppa == UNMAPPED_PPA || !same_flash(f, prev, p))) {
			struct fast_cursor *c = &f->dies[die_id(f, prev)].user;
			u64 ready = start;
			if (c->pending && c->block == prev.g.blk &&
			    (c->page - c->pending) / s->pgs_per_flashpg ==
				prev.g.pg / s->pgs_per_flashpg)
				ready = close_flash_page(f, die_id(f, prev), false, start, req->sq_id);
			end = max(end, flash_cmd(f, prev, NAND_READ, USER_IO, ready, bytes, true));
			bytes = 0;
		}
		if (p.ppa != UNMAPPED_PPA) {
			if (!bytes)
				prev = p;
			bytes += s->pgsz;
			f->read_pages++;
		}
	}
	ret->status = NVME_SC_SUCCESS;
	ret->nsecs_target = end;
}

bool conv_proc_nvme_io_cmd(struct nvmev_ns *ns, struct nvmev_request *req,
			   struct nvmev_result *ret)
{
	struct fast_ftl *f = ns->ftls;
	u64 lba = le64_to_cpu(req->cmd->rw.slba);
	u64 sectors = (u64)le16_to_cpu(req->cmd->rw.length) + 1;
	ret->status = NVME_SC_SUCCESS;
	ret->nsecs_target = req->nsecs_start;
	if (req->cmd->common.opcode == nvme_cmd_flush) {
		ret->nsecs_target = flush_all(f, req->nsecs_start, req->sq_id);
		return true;
	}
	if (lba >= ns->size / LBA_SIZE || sectors > ns->size / LBA_SIZE - lba) {
		ret->status = NVME_SC_LBA_RANGE;
		return true;
	}
	switch (req->cmd->common.opcode) {
	case nvme_cmd_write:
		return fast_write(ns, req, ret);
	case nvme_cmd_read:
		fast_read(ns, req, ret);
		return true;
	default:
		ret->status = NVME_SC_INVALID_OPCODE;
		return true;
	}
}

void conv_init_namespace(struct nvmev_ns *ns, u32 id, u64 size, void *addr, u32 cpu)
{
	struct fast_ftl *f = kzalloc(sizeof(*f), GFP_KERNEL);
	struct ssdparams s;
	u32 die;
	u64 lpn;
	NVMEV_ASSERT(f);
	ssd_init_params(&s, size, 1);
	ssd_init(&f->ssd, &s, cpu);
	f->placement = fast_placement;
	f->infer_overwrite = fast_infer_overwrite;
	f->map = vmalloc(array_size(s.tt_pgs, sizeof(*f->map)));
	f->rmap = vmalloc(array_size(s.tt_pgs, sizeof(*f->rmap)));
	f->dies = kcalloc(s.tt_luns, sizeof(*f->dies), GFP_KERNEL);
	NVMEV_ASSERT(f->map && f->rmap && f->dies);
	for (lpn = 0; lpn < s.tt_pgs; lpn++) {
		f->map[lpn].ppa = UNMAPPED_PPA;
		f->rmap[lpn] = INVALID_LPN;
	}
	for (die = 0; die < s.tt_luns; die++) {
		struct fast_die *d = &f->dies[die];
		d->state = kcalloc(s.blks_per_pl, sizeof(*d->state), GFP_KERNEL);
		NVMEV_ASSERT(d->state);
		d->free_blocks = s.blks_per_pl;
		d->user.block = d->gc.block = U32_MAX;
	}
	ns->id = id;
	ns->csi = NVME_CSI_NVM;
	ns->nr_parts = 1;
	ns->ftls = f;
	ns->size = round_down(size * 100 / 107, 4096);
	ns->mapped = addr;
	ns->proc_io_cmd = conv_proc_nvme_io_cmd;
	NVMEV_INFO("FAST24 profile onfi=%d placement=%d physical=%llu logical=%llu channels=%d dies=%lu flash_page=%d buffer=%llu\n",
		f->ssd.onfi_collision, f->placement, size, ns->size, s.nchs, s.tt_luns,
		s.pgs_per_flashpg * s.pgsz, s.write_buffer_size);
}

void conv_remove_namespace(struct nvmev_ns *ns)
{
	struct fast_ftl *f = ns->ftls;
	u32 die;
	for (die = 0; die < f->ssd.sp.tt_luns; die++)
		kfree(f->dies[die].state);
	kfree(f->dies);
	vfree(f->map);
	vfree(f->rmap);
	ssd_remove(&f->ssd);
	kfree(f);
	ns->ftls = NULL;
}

void fast24_debug(struct seq_file *m, struct nvmev_ns *ns)
{
	struct fast_ftl *f = ns->ftls;
	u32 ch, die;
	seq_printf(m, "fast24 onfi=%d placement=%d writes=%llu append_hints=%llu overwrite_hints=%llu applied=%llu missing=%llu rejected=%llu read_pages=%llu infer_overwrite=%d inferred_candidates=%llu inferred_applied=%llu inferred_changed=%llu\n",
		f->ssd.onfi_collision, f->placement, f->writes, f->append_hints,
		f->overwrite_hints, f->applied_hints, f->missing_hints, f->rejected, f->read_pages,
		f->infer_overwrite, f->inferred_candidates, f->inferred_applied, f->inferred_changed);
	for (ch = 0; ch < f->ssd.sp.nchs; ch++) {
		struct ssd_channel *c = &f->ssd.ch[ch];
		struct onfi_target t;
		unsigned long flags;
		spin_lock_irqsave(&c->timing_lock, flags);
		t = c->onfi;
		spin_unlock_irqrestore(&c->timing_lock, flags);
		seq_printf(m, "onfi channel=%u wait_events=%llu wait_ns=%llu max_wait_ns=%llu\n",
			ch, t.program_wait_events, t.program_wait_ns, t.program_wait_max_ns);
	}
	for (die = 0; die < f->ssd.sp.tt_luns; die++) {
		struct fast_die *d = &f->dies[die];
		seq_printf(m, "die id=%u reads=%llu programs=%llu erases=%llu gc_count=%llu gc_pages=%llu live_pages=%llu free_blocks=%u\n",
			die, d->reads, d->programs, d->erases, d->gc_count, d->gc_pages,
			d->live_pages, d->free_blocks);
	}
}
