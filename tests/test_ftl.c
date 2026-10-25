/* SPDX-License-Identifier: GPL-2.0-only */
#define NVMEV_FAST24_TEST
#include "../fast24_ftl.c"

static void io(struct nvmev_ns *ns, unsigned op, u64 page, u32 count, u32 hint, u64 prev)
{
	struct nvme_command c = { .rw = { .opcode=op, .slba=page*8,
		.length=count*8-1, .control=hint, .rsvd2=prev*8 } };
	struct nvmev_request r = { .cmd=&c, .sq_id=1, .nsecs_start=1000 };
	struct nvmev_result out;
	assert(conv_proc_nvme_io_cmd(ns,&r,&out));
	assert(out.status==NVME_SC_SUCCESS);
}

static void invariant(struct nvmev_ns *ns)
{
	struct fast_ftl *f=ns->ftls;
	u64 lpn, valid=0, counted=0;
	u32 d,b,pg;
	for(lpn=0;lpn<f->ssd.sp.tt_pgs;lpn++) if(f->map[lpn].ppa!=UNMAPPED_PPA) {
		struct ppa p=f->map[lpn];
		assert(get_pg(&f->ssd,&p)->status==PG_VALID);
		assert(f->rmap[fast_page_index(f,p)]==lpn);
		valid++;
	}
	for(d=0;d<f->ssd.sp.tt_luns;d++) {
		u64 live=0;
		u32 free_count=0;
		for(b=0;b<f->ssd.sp.blks_per_pl;b++) {
			struct nand_block *blk=block_at(f,d,b);
			u32 v=0,inv=0;
			for(pg=0;pg<f->ssd.sp.pgs_per_blk;pg++) {
				v+=blk->pg[pg].status==PG_VALID;
				inv+=blk->pg[pg].status==PG_INVALID;
			}
			assert(v==(u32)blk->vpc && inv==(u32)blk->ipc);
			live+=v;
			free_count+=f->dies[d].state[b]==BLOCK_FREE;
		}
		assert(free_count==f->dies[d].free_blocks);
		assert(live==f->dies[d].live_pages);
		counted+=live;
	}
	assert(valid==counted);
}

static void raw_overwrite_boundary(void)
{
	unsigned infer, mode;
	for (infer=0; infer<2; infer++) for (mode=0; mode<2; mode++) {
		struct nvmev_ns ns={0};
		struct fast_ftl *f;
		u32 old_die, next, prev_die;
		fast_placement=mode;
		fast_infer_overwrite=infer;
		conv_init_namespace(&ns,0,4*1024*1024,NULL,0);
		f=ns.ftls;
		io(&ns,nvme_cmd_write,0,24,0,0);
		assert(!f->inferred_candidates && !f->inferred_applied);
		old_die=die_id(f,f->map[0]); next=f->next_die;
		assert(old_die!=next);
		io(&ns,nvme_cmd_write,0,1,0,0);
		assert(die_id(f,f->map[0])==(mode && infer ? old_die : next));
		assert(f->inferred_candidates==infer && f->inferred_applied==(mode && infer));
		assert(f->inferred_changed==(mode && infer));
		assert(!f->overwrite_hints && !f->applied_hints);
		/* Explicit append has precedence even when replacing an existing LBA. */
		prev_die=die_id(f,f->map[15]); next=f->next_die;
		io(&ns,nvme_cmd_write,0,1,FAST24_APPEND,15);
		assert(die_id(f,f->map[0])==(mode ? (prev_die+1)%f->ssd.sp.tt_luns : next));
		assert(f->inferred_candidates==infer);
		/* An unmapped LBA is never inferred as an overwrite. */
		next=f->next_die;
		io(&ns,nvme_cmd_write,128,1,0,0);
		assert(die_id(f,f->map[128])==next);
		assert(f->inferred_candidates==infer);
		invariant(&ns);
		conv_remove_namespace(&ns);
	}
}

int main(void)
{
	unsigned mode, infer;
	raw_overwrite_boundary();
	for(infer=0;infer<2;infer++) for(mode=0;mode<2;mode++) {
		struct nvmev_ns ns={0};
		struct fast_ftl *f;
		u32 i, d, saved[64];
		u64 gc_count=0;
		fast_placement=mode;
		fast_infer_overwrite=infer;
		conv_init_namespace(&ns,0,4*1024*1024,NULL,0);
		f=ns.ftls;
		io(&ns,nvme_cmd_write,0,64,0,0);
		for(i=0;i<64;i++) saved[i]=die_id(f,f->map[i]);
		/* Force repeated per-die block exhaustion and GC, with partial
		 * flash pages, overwrites, flush padding and intervening reads. */
		for(i=0;i<6000;i++) {
			u32 page=(i*37)%64;
			io(&ns,nvme_cmd_write,page,1,infer ? 0 : FAST24_OVERWRITE,0);
			if(mode) assert(die_id(f,f->map[page])==saved[page]);
			if(i%7==0) io(&ns,nvme_cmd_read,page,1,0,0);
			if(i%13==0) io(&ns,nvme_cmd_flush,0,1,0,0);
			if(i%43==0) invariant(&ns);
		}
		io(&ns,nvme_cmd_flush,0,1,0,0);
		assert(f->ssd.write_buffer->remaining==f->ssd.write_buffer->size);
		for(d=0;d<f->ssd.sp.tt_luns;d++) gc_count+=f->dies[d].gc_count;
		assert(gc_count>0);
		assert(f->inferred_candidates==(infer ? 6000 : 0));
		assert(f->inferred_applied==(infer && mode ? 6000 : 0));
		assert(f->overwrite_hints==(infer ? 0 : 6000));
		invariant(&ns);
		conv_remove_namespace(&ns);
	}
	puts("Actual FTL: explicit/inferred overwrite affinity, opt-in/precedence, mapping/rmap, buffering and GC: PASS");
}
