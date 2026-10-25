/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NVMEV_FAST24_PLACEMENT_H
#define NVMEV_FAST24_PLACEMENT_H

/* CDW12 bits 24/25, i.e. control bits 8/9, match the FAST24 artifact.
 * CDW2/3 carry the preceding file block's LBA for append writes.
 */
#define FAST24_APPEND (1U << 8)
#define FAST24_OVERWRITE (1U << 9)

static inline unsigned int fast24_select_die(int enabled, unsigned int control,
		unsigned int next, int old_die, int previous_die, unsigned int dies,
		int first_page)
{
	if (!enabled)
		return next;
	if ((control & FAST24_OVERWRITE) && old_die >= 0)
		return (unsigned int)old_die;
	if (first_page && (control & FAST24_APPEND) && previous_die >= 0)
		return ((unsigned int)previous_die + 1) % dies;
	return next;
}
#endif
