// SPDX-License-Identifier: GPL-2.0-only
/* Controlled FAST24 write patterns using the original CDW hint ABI.
 * Reads are handed to fio via an iolog, so preparation ioctl overhead is
 * not confused with asynchronous read performance.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <linux/fs.h>
#include <linux/nvme_ioctl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>
#include "../fast24_placement.h"

#define UNIT (32U * 1024)
#define STRIPE (8U * UNIT)
#define PIECES 256U
#define TARGET_BASE (64ULL * 1024 * 1024)
#define DUMMY_BASE (128ULL * 1024 * 1024)

static int fd, nsid;
static void *buffer;
static uint64_t capacity, rng = 1;
static unsigned random_max_units = 1024;

static void fail(const char *s)
{
	perror(s);
	exit(1);
}

static uint32_t random_unit(void)
{
	rng ^= rng << 13;
	rng ^= rng >> 7;
	rng ^= rng << 17;
	return 1 + rng % random_max_units;
}

static double seconds(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static void snapshot(const char *iolog, const char *phase)
{
	char path[4096], line[4096];
	FILE *in = fopen("/proc/nvmev/debug", "r"), *out;
	if (!in)
		fail("open counters");
	if (snprintf(path, sizeof(path), "%s.%s.stats", iolog, phase) >= (int)sizeof(path))
		exit(1);
	out = fopen(path, "w");
	if (!out)
		fail("snapshot counters");
	while (fgets(line, sizeof(line), in))
		fputs(line, out);
	if (ferror(in) || fclose(out))
		fail("snapshot counters");
	fclose(in);
}

static void command(unsigned opcode, uint64_t offset, uint32_t bytes,
		    unsigned hints, uint64_t previous)
{
	struct nvme_passthru_cmd c = {0};
	int rc;
	if (bytes && (offset > capacity || bytes > capacity - offset)) {
		fprintf(stderr, "command outside namespace\n");
		exit(1);
	}
	c.opcode = opcode;
	c.nsid = nsid;
	c.addr = bytes ? (uintptr_t)buffer : 0;
	c.data_len = bytes;
	c.cdw10 = (uint32_t)(offset / 512);
	c.cdw11 = (uint32_t)((offset / 512) >> 32);
	c.cdw12 = bytes ? (bytes / 512 - 1) | hints << 16 : 0;
	c.cdw2 = (uint32_t)(previous / 512);
	c.cdw3 = (uint32_t)((previous / 512) >> 32);
	c.timeout_ms = 30000;
	rc = ioctl(fd, NVME_IOCTL_IO_CMD, &c);
	if (rc < 0)
		fail("NVMe ioctl");
	if (rc) {
		fprintf(stderr, "NVMe status 0x%x opcode=%u offset=%" PRIu64 "\n", rc, opcode, offset);
		exit(1);
	}
}

static void write_extent(uint64_t offset, uint64_t bytes, unsigned hint, uint64_t previous,
			 unsigned char value)
{
	memset(buffer, value, 256 * 1024);
	while (bytes) {
		uint32_t chunk = bytes < 256 * 1024 ? bytes : 256 * 1024;
		command(1, offset, chunk, hint, previous);
		previous = offset + chunk - 4096;
		offset += chunk;
		bytes -= chunk;
		/* Each append continuation refers to the last block just written. */
	}
}

static void check_device(const char *device)
{
	char path[512], model[256];
	const char *name = strrchr(device, '/');
	FILE *f;
	name = name ? name + 1 : device;
	snprintf(path, sizeof(path), "/sys/class/block/%s/device/model", name);
	f = fopen(path, "r");
	if (!f || !fgets(model, sizeof(model), f))
		fail("read NVMe model");
	fclose(f);
	model[strcspn(model, " \t\r\n")] = 0;
	if (strcmp(model, "NVMeVirt_FAST24")) {
		fprintf(stderr, "refusing non-NVMeVirt device: %s", model);
		exit(1);
	}
	fd = open(device, O_RDWR | O_EXCL);
	if (fd < 0)
		fail("open exclusive namespace");
	nsid = ioctl(fd, NVME_IOCTL_ID);
	if (nsid <= 0 || ioctl(fd, BLKGETSIZE64, &capacity))
		fail("namespace properties");
}

int main(int argc, char **argv)
{
	uint64_t offsets[PIECES], dummy = DUMMY_BASE, dummy_bytes = 0;
	unsigned i;
	int overwrite, random, contiguous;
	double begin, construction, verified;
	FILE *log;
	if (argc != 5 && argc != 6) {
		fprintf(stderr, "usage: %s DEVICE contiguous|append_worst|append_random|overwrite_worst|overwrite_random SEED IOLOG [RANDOM_MAX_UNITS]\n", argv[0]);
		return 2;
	}
	if (argc == 6) random_max_units = strtoul(argv[5], NULL, 10);
	if (!random_max_units || random_max_units > 1024) return 2;
	contiguous = !strcmp(argv[2], "contiguous");
	overwrite = !strncmp(argv[2], "overwrite_", 10);
	random = strstr(argv[2], "random") != NULL;
	if (!contiguous && strcmp(argv[2], "append_worst") && strcmp(argv[2], "append_random") &&
	    strcmp(argv[2], "overwrite_worst") && strcmp(argv[2], "overwrite_random"))
		return 2;
	rng = strtoull(argv[3], NULL, 10);
	if (!rng)
		return 2;
	check_device(argv[1]);
	if (posix_memalign(&buffer, 4096, 256 * 1024))
		return 1;
	for (i = 0; i < PIECES; i++)
		offsets[i] = TARGET_BASE + (uint64_t)i * (contiguous || overwrite ? UNIT : STRIPE);
	snapshot(argv[4], "before");
	begin = seconds();
	if (overwrite)
		write_extent(TARGET_BASE, (uint64_t)PIECES * UNIT, 0, 0, 0x5a);
	for (i = 0; i < PIECES; i++) {
		unsigned hint = overwrite ? FAST24_OVERWRITE : (i ? FAST24_APPEND : 0);
		uint64_t interference = random ? (uint64_t)random_unit() * UNIT : STRIPE - UNIT;
		write_extent(offsets[i], UNIT, hint, i ? offsets[i - 1] + UNIT - 4096 : 0, i);
		if (!contiguous && i + 1 < PIECES) {
			write_extent(dummy, interference, 0, 0, 0xa5);
			dummy += interference;
			dummy_bytes += interference;
		}
	}
	command(0, 0, 0, 0, 0); /* flush pending partial programs before reads */
	construction = seconds() - begin;
	snapshot(argv[4], "constructed");
	/* Actual data verification; every piece has a distinct byte pattern. */
	begin = seconds();
	for (i = 0; i < PIECES; i++) {
		unsigned k;
		memset(buffer, 0, UNIT);
		command(2, offsets[i], UNIT, 0, 0);
		for (k = 0; k < UNIT; k++)
			if (((unsigned char *)buffer)[k] != (unsigned char)i) {
				fprintf(stderr, "verification failed piece=%u byte=%u\n", i, k);
				return 1;
			}
	}
	verified = seconds() - begin;
	snapshot(argv[4], "verified");
	log = fopen(argv[4], "w");
	if (!log)
		fail("open iolog");
	fprintf(log, "fio version 2 iolog\n%s add\n%s open\n", argv[1], argv[1]);
	for (i = 0; i < PIECES; i++)
		fprintf(log, "%s read %" PRIu64 " %u\n", argv[1], offsets[i], UNIT);
	/* EOF drains outstanding libaio requests. An explicit iolog close in
	 * fio 3.28 loses the last QD-1 completions (also documented next door).
	 */
	if (fclose(log))
		fail("write iolog");
	printf("{\"case\":\"%s\",\"target_bytes\":%u,\"dummy_bytes\":%" PRIu64
	       ",\"construction_seconds\":%.9f,\"verify_seconds\":%.9f,\"verified\":true,"
	       "\"capacity_bytes\":%" PRIu64 "}\n",
	       argv[2], PIECES * UNIT, dummy_bytes, construction, verified, capacity);
	free(buffer);
	close(fd);
	return 0;
}
