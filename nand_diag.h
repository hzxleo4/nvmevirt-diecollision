/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef NVMEV_NAND_DIAG_H
#define NVMEV_NAND_DIAG_H

/* Observers only: none of these fields participate in resource scheduling.
 * All times are ns. Stage costs partition one NAND command's modeled latency,
 * not application wall time. Histogram bin i is (2^(i-1), 2^i] us, with
 * bin 0 = (0, 1] us and the last bin including overflow. Zero waits are absent.
 */
#define ND_BINS 20
enum nd_stage { ND_LUN, ND_INPUT, ND_ONFI, ND_ARRAY, ND_CH_LATE,
	ND_CH_QUEUE, ND_CH_SERVICE, ND_PCIE, ND_STAGES };
enum nd_op { ND_READ, ND_PROGRAM, ND_OTHER };

struct nd_event {
	unsigned long long seq, start, lun_ready, input_ready, onfi_ready;
	unsigned long long array_start, array_end, data_start, data_end, end;
	unsigned long long stage[ND_STAGES];
	unsigned long long previous_seq, blocker_seq, blocker_start;
	unsigned long long blocker_array_start, blocker_array_end, blocker_end;
	unsigned int lun, op, previous_op, blocker_lun, bytes, io_type;
};

struct nd_stats {
	unsigned long long ops, bytes, total_ns, stage[ND_STAGES], invalid;
	unsigned long long lun_events, after_read_ns, after_program_ns, after_other_ns;
	unsigned long long onfi_events, cross_events, same_events;
	unsigned long long blocker_queued_ns, blocker_sense_ns, blocker_output_ns;
	unsigned long long opportunity_events, opportunity_ns;
	unsigned long long onfi_hist[ND_BINS], lun_hist[ND_BINS], total_hist[ND_BINS];
};

static inline unsigned long long nd_wait(unsigned long long end,
					unsigned long long start)
{
	return end > start ? end - start : 0;
}

static inline void nd_hist_add(unsigned long long *hist, unsigned long long ns)
{
	unsigned int bin;
	if (!ns)
		return;
	bin = ns <= 1000 ? 0 : 64 - __builtin_clzll((ns - 1) / 1000);
	if (bin >= ND_BINS)
		bin = ND_BINS - 1;
	hist[bin]++;
}

static inline unsigned long long nd_overlap(unsigned long long a, unsigned long long b,
					   unsigned long long c, unsigned long long d)
{
	unsigned long long start = a > c ? a : c, end = b < d ? b : d;
	return nd_wait(end, start);
}

static inline void nd_record(struct nd_stats *s, const struct nd_event *e)
{
	unsigned int i;
	unsigned long long sum = 0, opportunity;
	s->ops++;
	s->bytes += e->bytes;
	s->total_ns += nd_wait(e->end, e->start);
	for (i = 0; i < ND_STAGES; i++) {
		s->stage[i] += e->stage[i];
		sum += e->stage[i];
	}
	s->invalid += e->end < e->start || sum != e->end - e->start;
	if (e->stage[ND_LUN]) {
		s->lun_events++;
		if (e->previous_op == ND_READ)
			s->after_read_ns += e->stage[ND_LUN];
		else if (e->previous_op == ND_PROGRAM)
			s->after_program_ns += e->stage[ND_LUN];
		else
			s->after_other_ns += e->stage[ND_LUN];
	}
	if (e->stage[ND_ONFI]) {
		unsigned long long queued = nd_overlap(e->input_ready, e->onfi_ready, 0, e->blocker_array_start);
		unsigned long long sense = nd_overlap(e->input_ready, e->onfi_ready, e->blocker_array_start, e->blocker_array_end);
		unsigned long long output = nd_overlap(e->input_ready, e->onfi_ready, e->blocker_array_end, e->blocker_end);
		s->onfi_events++;
		s->blocker_queued_ns += queued;
		s->blocker_sense_ns += sense;
		s->blocker_output_ns += output;
		s->invalid += queued + sense + output != e->stage[ND_ONFI];
		if (e->blocker_lun == e->lun)
			s->same_events++;
		else
			s->cross_events++;
	}
	/* This is a local opportunity on the current schedule. OFF observations
	 * are not a replay of the ON schedule, nor causal saved wall time. */
	opportunity = e->op == ND_PROGRAM ? nd_wait(e->blocker_end, e->input_ready) : 0;
	if (opportunity) {
		s->opportunity_events++;
		s->opportunity_ns += opportunity;
	}
	nd_hist_add(s->onfi_hist, e->stage[ND_ONFI]);
	nd_hist_add(s->lun_hist, e->stage[ND_LUN]);
	nd_hist_add(s->total_hist, nd_wait(e->end, e->start));
}
#endif
