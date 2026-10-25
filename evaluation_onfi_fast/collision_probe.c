// SPDX-License-Identifier: GPL-2.0-only
/* Positive control for the ONFI timing path, NOT a FAST24 paper workload.
 * Alternating reads of an immutable 8 MiB target and writes to a separate
 * 8 MiB region. Same fixed request stream and QD in every feature group.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/aio_abi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#define BYTES 32768
#define PIECES 256
#define DEPTH 64
#define OPS 16384
#define WRITE_BASE (256ULL * 1024 * 1024)
static struct iocb cb[DEPTH];
static unsigned char *data;
static uint64_t offsets[PIECES];
static int active[DEPTH], ids[DEPTH];
static uint64_t issued[DEPTH], latency[OPS];
static void fail(const char *what) { perror(what); exit(1); }
static uint64_t now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
static int compare(const void *a, const void *b)
{
	uint64_t x = *(const uint64_t *)a, y = *(const uint64_t *)b;
	return (x > y) - (x < y);
}
static void verify(const unsigned char *buf, unsigned char value)
{
	for (int k = 0; k < BYTES; k++)
		if (buf[k] != value) {
			fprintf(stderr, "data mismatch byte=%d expected=%u actual=%u\n", k, value, buf[k]);
			exit(1);
		}
}
static void check_model(const char *device)
{
	char path[1024], model[128];
	const char *name = strrchr(device, '/');
	if (!name) exit(1);
	snprintf(path, sizeof(path), "/sys/class/block/%s/device/model", name + 1);
	FILE *f = fopen(path, "r");
	if (!f || !fgets(model, sizeof(model), f)) fail("model");
	fclose(f);
	model[strcspn(model, " \t\r\n")] = 0;
	if (strcmp(model, "NVMeVirt_FAST24")) {
		fprintf(stderr, "refusing non-experiment device\n");
		exit(1);
	}
}
static void probe(int fd, int count)
{
	aio_context_t ctx = 0;
	struct io_event events[DEPTH];
	int submitted = 0, completed = 0;
	uint64_t start, end, drained, sum = 0;
	if (syscall(SYS_io_setup, DEPTH, &ctx)) fail("io_setup");
	start = now();
	while (completed < count) {
		for (int slot = 0; slot < DEPTH && submitted < count; slot++) {
			if (active[slot]) continue;
			int id = submitted, writing = id & 1;
			/* The read leads by four flash pages: opposite LUN, same
			 * channel in the 4-channel x 2-LUN round-robin layout. */
			unsigned piece = (id / 2 + (writing ? 0 : 4)) % PIECES;
			unsigned char *buf = data + slot * BYTES;
			if (writing) memset(buf, 0xa5, BYTES);
			cb[slot] = (struct iocb){.aio_data = slot,
				.aio_lio_opcode = writing ? IOCB_CMD_PWRITE : IOCB_CMD_PREAD,
				.aio_fildes = fd, .aio_buf = (uintptr_t)buf, .aio_nbytes = BYTES,
				.aio_offset = writing ? WRITE_BASE + piece * BYTES : offsets[piece]};
			struct iocb *ptr = &cb[slot];
			issued[slot] = now();
			if (syscall(SYS_io_submit, ctx, 1, &ptr) != 1) fail("io_submit");
			active[slot] = 1;
			ids[slot] = id;
			submitted++;
		}
		long n = syscall(SYS_io_getevents, ctx, 1, DEPTH, events, NULL);
		if (n < 0 && errno == EINTR) continue;
		if (n <= 0) fail("io_getevents");
		uint64_t t = now();
		for (int i = 0; i < n; i++) {
			unsigned slot = events[i].data;
			if (slot >= DEPTH || !active[slot] || events[i].res != BYTES || events[i].res2) {
				fprintf(stderr, "invalid completion res=%lld\n", (long long)events[i].res);
				exit(1);
			}
			latency[ids[slot]] = t - issued[slot];
			if (!(ids[slot] & 1))
				verify(data + slot * BYTES, (ids[slot] / 2 + 4) % PIECES);
			active[slot] = 0;
			completed++;
		}
	}
	end = now();
	if (fsync(fd)) fail("final flush");
	drained = now();
	if (syscall(SYS_io_destroy, ctx)) fail("io_destroy");
	/* Final verification checks the whole write region and immutable target. */
	for (int i = 0; i < PIECES; i++) {
		if (pread(fd, data, BYTES, WRITE_BASE + i * BYTES) != BYTES) fail("verify write read");
		verify(data, 0xa5);
		if (pread(fd, data, BYTES, offsets[i]) != BYTES) fail("verify target read");
		verify(data, i);
	}
	for (int i = 0; i < count; i++) sum += latency[i];
	qsort(latency, count, sizeof(*latency), compare);
	printf("{\"suite\":\"onfi_positive_control\",\"completed\":%d,\"read_bytes\":%llu,"
	       "\"write_bytes\":%llu,\"elapsed_ns\":%" PRIu64 ",\"drained_ns\":%" PRIu64
	       ",\"total_MiB_s_including_flush\":%.6f,\"mean_submission_to_reap_us\":%.6f,"
	       "\"p99_submission_to_reap_us\":%.6f,\"verified\":true}\n",
	       completed, (unsigned long long)count / 2 * BYTES, (unsigned long long)count / 2 * BYTES,
	       end - start, drained - start, (double)count * BYTES / 1048576 * 1e9 / (drained - start),
	       (double)sum / count / 1000, (double)latency[(count * 99 + 99) / 100 - 1] / 1000);
}
int main(int argc, char **argv)
{
	char selected[512] = "", line[1024], device[512], op[32];
	int fd, n = 0, self;
	if (argc != 2) {
		fprintf(stderr, "usage: %s IOLOG|--self-test\n", argv[0]);
		return 2;
	}
	self = !strcmp(argv[1], "--self-test");
	if (posix_memalign((void **)&data, 4096, DEPTH * BYTES)) return 1;
	if (self) {
		char temp[] = "/tmp/nvmev-collision-probe.XXXXXX";
		fd = mkstemp(temp);
		if (fd < 0) fail("mkstemp");
		for (n = 0; n < PIECES; n++) {
			offsets[n] = (uint64_t)n * BYTES;
			memset(data, n, BYTES);
			if (write(fd, data, BYTES) != BYTES) fail("selftest preparation");
		}
		if (fsync(fd)) fail("selftest fsync");
		close(fd);
		fd = open(temp, O_RDWR | O_DIRECT);
		unlink(temp);
	} else {
		FILE *log = fopen(argv[1], "r");
		if (!log) fail("iolog");
		while (fgets(line, sizeof(line), log)) {
			unsigned long long offset;
			unsigned bytes;
			if (sscanf(line, "%511s %31s %llu %u", device, op, &offset, &bytes) != 4) continue;
			if (strcmp(op, "read") || bytes != BYTES || n == PIECES ||
			    offset % 4096 || offset >= WRITE_BASE || BYTES > WRITE_BASE - offset) return 2;
			if (*selected && strcmp(selected, device)) return 2;
			strcpy(selected, device);
			offsets[n++] = offset;
		}
		fclose(log);
		if (n != PIECES) return 2;
		check_model(selected);
		fd = open(selected, O_RDWR | O_DIRECT | O_EXCL);
	}
	if (fd < 0) fail("exclusive open");
	probe(fd, self ? 512 : OPS);
	close(fd);
	free(data);
	return 0;
}
