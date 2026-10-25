/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NVMEV_ONFI_MODEL_H
#define NVMEV_ONFI_MODEL_H

/* Shared by the emulator and the deterministic userspace timing tests.
 * One instance is a NAND target (two LUNs in the FAST24 profile).
 * Data-channel and same-LUN resource reservations remain separate.
 */
struct onfi_target {
	unsigned long long read_data_until;
	unsigned long long program_input_until;
	unsigned long long program_wait_events;
	unsigned long long program_wait_ns;
	unsigned long long program_wait_max_ns;
};

static inline unsigned long long onfi_read_start(const struct onfi_target *t,
						unsigned long long ready)
{
	/* A read may overlap tPROG, but not program command/data input. Also
	 * prevents a later-dispatched read being backdated before a program
	 * already reserved in the future (which would invalidate its register).
	 */
	return ready > t->program_input_until ? ready : t->program_input_until;
}

static inline unsigned long long onfi_program_start(struct onfi_target *t,
						unsigned long long ready, int enabled)
{
	if (enabled && t->read_data_until > ready) {
		unsigned long long wait = t->read_data_until - ready;
		t->program_wait_events++;
		t->program_wait_ns += wait;
		if (wait > t->program_wait_max_ns)
			t->program_wait_max_ns = wait;
		return t->read_data_until;
	}
	return ready;
}

static inline void onfi_read_done(struct onfi_target *t, unsigned long long data_end)
{
	if (data_end > t->read_data_until)
		t->read_data_until = data_end;
}

static inline void onfi_program_input_done(struct onfi_target *t,
					  unsigned long long input_end)
{
	if (input_end > t->program_input_until)
		t->program_input_until = input_end;
}
#endif
