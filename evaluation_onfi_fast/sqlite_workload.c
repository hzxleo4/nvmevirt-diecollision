// SPDX-License-Identifier: GPL-2.0-only
/* FAST24 SQLite protocol: descending IDs, four text columns (~16 KiB),
 * journal_mode=OFF, synchronous=ON, one transaction per insert, and
 * an optional synchronous 100 KiB dummy-file append after each insert.
 * Deterministic payloads and checked errors replace the artifact's time seed.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sqlite3.h>

static const int lens[] = {4096, 4096, 4096, 4094};
static char values[4][4097];
static uint64_t rng;
static void fail(const char *s) { perror(s); exit(1); }
static double now(void)
{
	struct timespec t;
	if (clock_gettime(CLOCK_MONOTONIC, &t)) fail("clock");
	return t.tv_sec + t.tv_nsec / 1e9;
}
static void payload(void)
{
	for (int col = 0; col < 4; col++) {
		for (int i = 0; i < lens[col]; i++) {
			rng ^= rng << 13; rng ^= rng >> 7; rng ^= rng << 17;
			values[col][i] = 'a' + rng % 26;
		}
		values[col][lens[col]] = 0;
	}
}
static void sql(sqlite3 *db, const char *q)
{
	char *error = NULL;
	if (sqlite3_exec(db, q, NULL, NULL, &error) != SQLITE_OK) {
		fprintf(stderr, "SQLite: %s\n", error ? error : sqlite3_errmsg(db));
		sqlite3_free(error); exit(1);
	}
}
int main(int argc, char **argv)
{
	if (argc != 7) {
		fprintf(stderr, "usage: %s build|read|verify DIR RECORDS SEED DUMMY_BYTES SYNCFS\n", argv[0]);
		return 2;
	}
	int records = atoi(argv[3]), dummy_bytes = atoi(argv[5]);
	int build = !strcmp(argv[1], "build"), read = !strcmp(argv[1], "read");
	int check = !strcmp(argv[1], "verify"), sync_fs = atoi(argv[6]);
	char dbpath[4096], dummypath[4096];
	sqlite3 *db = NULL;
	rng = strtoull(argv[4], NULL, 10);
	if ((!build && !read && !check) || records < 1 || records > 10000 ||
	    !rng || dummy_bytes < 0 || dummy_bytes > 102400) return 2;
	if (snprintf(dbpath, sizeof(dbpath), "%s/testdb.db", argv[2]) >= (int)sizeof(dbpath) ||
	    snprintf(dummypath, sizeof(dummypath), "%s/dummy.data", argv[2]) >= (int)sizeof(dummypath)) return 2;
	double start = now(), elapsed;
	int flags = build ? SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE : SQLITE_OPEN_READONLY;
	if (build && !access(dbpath, F_OK)) { fprintf(stderr, "refusing existing database\n"); return 1; }
	if (sqlite3_open_v2(dbpath, &db, flags, NULL) != SQLITE_OK) {
		fprintf(stderr, "open: %s\n", sqlite3_errmsg(db)); return 1;
	}
	if (build) {
		char dummy[102400];
		memset(dummy, 0xa5, sizeof(dummy));
		int fd = open(dummypath, O_CREAT | O_EXCL | O_WRONLY, 0600);
		if (fd < 0) fail("dummy open");
		sql(db, "PRAGMA journal_mode=OFF; PRAGMA synchronous=ON;");
		sql(db, "CREATE TABLE DB1(id INT PRIMARY KEY, str1 VARCHAR(4096), str2 VARCHAR(4096), str3 VARCHAR(4096), str4 VARCHAR(4094));");
		for (int id = records - 1; id >= 0; id--) {
			char *q = NULL;
			payload();
			if (asprintf(&q, "INSERT INTO DB1 VALUES(%d,'%s','%s','%s','%s');", id,
			             values[0], values[1], values[2], values[3]) < 0) fail("asprintf");
			sql(db, q); free(q);
			if (dummy_bytes && (write(fd, dummy, dummy_bytes) != dummy_bytes || fdatasync(fd)))
				fail("dummy append");
		}
		if (sqlite3_close(db) != SQLITE_OK) return 1;
		if (sync_fs && syncfs(fd)) fail("syncfs");
		if (close(fd)) fail("dummy close");
		elapsed = now() - start;
		printf("{\"phase\":\"build\",\"records\":%d,\"seconds\":%.9f,\"records_s\":%.6f,"
		       "\"dummy_bytes\":%llu,\"sqlite_version\":\"%s\"}\n", records, elapsed, records / elapsed,
		       (unsigned long long)records * dummy_bytes, sqlite3_libversion());
	} else if (read) {
		/* Time the same SELECT as the artifact; database open and validation
		 * are outside this interval. Cache dropping is done by the runner. */
		start = now();
		sql(db, "SELECT * FROM DB1;");
		elapsed = now() - start;
		if (sqlite3_close(db) != SQLITE_OK) return 1;
		printf("{\"phase\":\"select\",\"records\":%d,\"seconds\":%.9f,\"records_s\":%.6f}\n",
		       records, elapsed, records / elapsed);
	} else {
		sqlite3_stmt *stmt = NULL;
		if (sqlite3_prepare_v2(db, "SELECT * FROM DB1 ORDER BY id DESC;", -1, &stmt, NULL) != SQLITE_OK) return 1;
		for (int id = records - 1; id >= 0; id--) {
			if (sqlite3_step(stmt) != SQLITE_ROW || sqlite3_column_int(stmt, 0) != id) return 1;
			payload();
			for (int col = 0; col < 4; col++) {
				const unsigned char *v = sqlite3_column_text(stmt, col + 1);
				if (!v || sqlite3_column_bytes(stmt, col + 1) != lens[col] || memcmp(v, values[col], lens[col])) {
					fprintf(stderr, "payload mismatch id=%d column=%d\n", id, col); return 1;
				}
			}
		}
		if (sqlite3_step(stmt) != SQLITE_DONE) return 1;
		sqlite3_finalize(stmt);
		if (sqlite3_prepare_v2(db, "PRAGMA integrity_check;", -1, &stmt, NULL) != SQLITE_OK ||
		    sqlite3_step(stmt) != SQLITE_ROW || strcmp((const char *)sqlite3_column_text(stmt, 0), "ok")) return 1;
		sqlite3_finalize(stmt); sqlite3_close(db);
		printf("{\"verified\":true,\"records\":%d}\n", records);
	}
	return 0;
}
