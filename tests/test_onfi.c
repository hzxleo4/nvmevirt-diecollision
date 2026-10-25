/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "../onfi_model.h"

int main(void)
{
	struct onfi_target t = {0}, other = {0}, off = {0};
	/* Read sensing ends at 36 us, but register remains live until 76 us. */
	onfi_read_done(&t, 76000);
	assert(onfi_program_start(&t, 40000, 1) == 76000);
	assert(t.program_wait_ns == 36000 && t.program_wait_events == 1);
	assert(onfi_program_start(&t, 76000, 1) == 76000);
	assert(t.program_wait_events == 1);
	/* Same-die ready time already includes the read: no extra ONFI wait. */
	assert(onfi_program_start(&t, 80000, 1) == 80000);
	/* Targets do not interfere. */
	assert(onfi_program_start(&other, 40000, 1) == 40000);
	onfi_read_done(&off, 76000);
	assert(onfi_program_start(&off, 40000, 0) == 40000);
	assert(off.program_wait_events == 0);
	/* Program data input ends at 100 us, program array stays busy until
	 * 285 us. A DIFFERENT die can start sensing at 100 us, not 285 us. */
	onfi_program_input_done(&t, 100000);
	assert(onfi_read_start(&t, 90000) == 100000);
	assert(onfi_read_start(&t, 110000) == 110000);
	/* A new read extends protection through its data output. */
	onfi_read_done(&t, 160000);
	onfi_read_done(&t, 150000);
	assert(onfi_program_start(&t, 110000, 1) == 160000);
	assert(t.program_wait_max_ns == 50000);
	puts("ONFI direction, data-output lifetime, target isolation: PASS");
	return 0;
}
