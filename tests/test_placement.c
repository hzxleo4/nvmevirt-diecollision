/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "../fast24_placement.h"
int main(void)
{
	assert(fast24_select_die(0, FAST24_APPEND, 4, -1, 1, 8, 1) == 4);
	assert(fast24_select_die(1, FAST24_APPEND, 4, -1, 1, 8, 1) == 2);
	assert(fast24_select_die(1, FAST24_APPEND, 4, -1, 7, 8, 1) == 0);
	assert(fast24_select_die(1, FAST24_APPEND, 4, -1, -1, 8, 1) == 4);
	assert(fast24_select_die(1, FAST24_APPEND, 4, -1, 1, 8, 0) == 4);
	/* Every overwritten mapping page retains its own die, even in a
	 * multi-page request whose previous mapping was not contiguous. */
	assert(fast24_select_die(1, FAST24_OVERWRITE, 4, 6, -1, 8, 1) == 6);
	assert(fast24_select_die(1, FAST24_OVERWRITE, 4, 2, -1, 8, 0) == 2);
	assert(fast24_select_die(1, FAST24_OVERWRITE, 4, -1, -1, 8, 1) == 4);
	puts("FAST24 append, wrap, overwrite, missing hint and OFF: PASS");
}
