/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "../nand_diag.h"

int main(void)
{
	struct nd_stats s = {0};
	/* Cross-LUN program: 10 us local queue, 70 us ONFI, 40 us
	 * transfer, 185 us array. The diagnostic partition must add to 305 us. */
	struct nd_event e = { .op=ND_PROGRAM, .lun=1, .blocker_lun=0,
		.start=1000, .input_ready=11000, .blocker_end=81000, .end=306000,
		.onfi_ready=81000, .blocker_array_start=40000, .blocker_array_end=76000,
		.previous_op=ND_READ, .bytes=32768,
		.stage={10000,0,70000,185000,0,0,40000,0} };
	nd_record(&s, &e);
	assert(!s.invalid && s.total_ns==305000 && s.ops==1);
	assert(s.cross_events==1 && s.same_events==0 && s.opportunity_ns==70000);
	assert(s.blocker_queued_ns==29000 && s.blocker_sense_ns==36000 && s.blocker_output_ns==5000);
	assert(s.after_read_ns==10000 && s.lun_hist[4]==1 && s.onfi_hist[7]==1);
	/* Local queue masks the target read; zero ONFI does not mean no wait. */
	e.input_ready=121000; e.end=346000; e.stage[ND_LUN]=120000;
	e.stage[ND_ONFI]=0; e.previous_op=ND_PROGRAM;
	nd_record(&s, &e);
	assert(!s.invalid && s.onfi_events==1 && s.lun_events==2);
	assert(s.after_program_ns==120000 && s.opportunity_events==1);
	/* OFF records an opportunity without charging that time to the request. */
	e.input_ready=11000; e.end=236000; e.stage[ND_LUN]=10000;
	nd_record(&s, &e);
	assert(!s.invalid && s.onfi_events==1 && s.opportunity_events==2);
	/* Include late emulator dispatch, channel queue and exposed PCIe tail. */
	e=(struct nd_event){.op=ND_READ, .start=100, .end=78100,
		.stage={10000,5000,0,36000,2000,10000,10000,5000}};
	nd_record(&s,&e);
	assert(!s.invalid && s.ops==4);
	e.end++; nd_record(&s,&e); assert(s.invalid==1);
	{ unsigned long long h[ND_BINS]={0};
	  nd_hist_add(h,0); nd_hist_add(h,1000); nd_hist_add(h,1001);
	  nd_hist_add(h,2000); nd_hist_add(h,2001); nd_hist_add(h,~0ULL);
	  assert(h[0]==1 && h[1]==2 && h[2]==1 && h[ND_BINS-1]==1); }
	puts("NAND diagnostics: exact latency partition, masked/cross-LUN waits, OFF opportunities, histogram edges: PASS");
	return 0;
}
