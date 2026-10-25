// SPDX-License-Identifier: GPL-2.0-only
/* Complete, nanosecond-timed Linux AIO pass over the same fio iolog.
 * Measures userspace submission-to-reap latency, not kernel completion time.
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

#define COUNT 256
#define BYTES 32768
static struct iocb cb[COUNT];
static uint64_t issued[COUNT], latency[COUNT];
static unsigned char *data;
static uint64_t now(void)
{
	struct timespec t;
	clock_gettime(CLOCK_MONOTONIC, &t);
	return (uint64_t)t.tv_sec * 1000000000 + t.tv_nsec;
}
static void fail(const char *what) { perror(what); exit(1); }
static int compare(const void *a, const void *b)
{
	uint64_t x=*(const uint64_t *)a,y=*(const uint64_t *)b;
	return (x>y)-(x<y);
}
static void pass(int fd, const uint64_t *offsets, int depth)
{
	aio_context_t ctx=0;
	struct io_event events[COUNT];
	int submitted=0,completed=0,i;
	uint64_t start,end,sum=0;
	if(syscall(SYS_io_setup,depth,&ctx)) fail("io_setup");
	for(i=0;i<COUNT;i++) {
		cb[i]=(struct iocb){.aio_data=i,.aio_lio_opcode=IOCB_CMD_PREAD,
			.aio_fildes=fd,.aio_buf=(uintptr_t)(data+i*BYTES),
			.aio_nbytes=BYTES,.aio_offset=offsets[i]};
	}
	start=now();
	while(completed<COUNT) {
		while(submitted<COUNT && submitted-completed<depth) {
			struct iocb *ptr=&cb[submitted];
			long rc;
			issued[submitted]=now();
			rc=syscall(SYS_io_submit,ctx,1,&ptr);
			if(rc!=1) fail("io_submit");
			submitted++;
		}
		long n=syscall(SYS_io_getevents,ctx,1,depth,events,NULL);
		if(n<0 && errno==EINTR) continue;
		if(n<=0) fail("io_getevents");
		uint64_t t=now();
		for(i=0;i<n;i++) {
			unsigned id=events[i].data;
			if(id>=COUNT || latency[id] || events[i].res!=BYTES || events[i].res2) {
				fprintf(stderr,"bad/duplicate completion id=%u res=%lld\n",id,(long long)events[i].res);
				exit(1);
			}
			latency[id]=t-issued[id];
			completed++;
		}
	}
	end=now();
	if(syscall(SYS_io_destroy,ctx)) fail("io_destroy");
	for(i=0;i<COUNT;i++) {
		int k;
		for(k=0;k<BYTES;k++) if(data[i*BYTES+k]!=(unsigned char)i) {
			fprintf(stderr,"data mismatch piece=%d byte=%d\n",i,k);
			exit(1);
		}
		sum+=latency[i];
	}
	qsort(latency,COUNT,sizeof(*latency),compare);
	printf("{\"io_bytes\":%u,\"completed\":%d,\"elapsed_ns\":%" PRIu64
	       ",\"MiB_s\":%.9f,\"mean_submission_to_reap_us\":%.6f,"
	       "\"p99_submission_to_reap_us\":%.6f,\"verified\":true}\n",
	       COUNT*BYTES,completed,end-start,8e9/(end-start),(double)sum/COUNT/1000,
	       (double)latency[253]/1000);
}

int main(int argc,char **argv)
{
	uint64_t offsets[COUNT];
	char device[512],line[1024];
	int fd,n=0,depth;
	FILE *log;
	if(argc!=3) {
		fprintf(stderr,"usage: %s IOLOG|--self-test QD\n",argv[0]);
		return 2;
	}
	depth=atoi(argv[2]);
	if(depth<1 || depth>COUNT) return 2;
	if(posix_memalign((void **)&data,4096,COUNT*BYTES)) return 1;
	if(!strcmp(argv[1],"--self-test")) {
		char temp[]="/tmp/nvmev-readpass.XXXXXX";
		fd=mkstemp(temp);
		if(fd<0) fail("mkstemp");
		for(n=0;n<COUNT;n++) {
			memset(data+n*BYTES,n,BYTES);
			offsets[n]=(uint64_t)n*BYTES;
		}
		if(write(fd,data,COUNT*BYTES)!=COUNT*BYTES || fsync(fd)) fail("selftest write");
		close(fd);
		fd=open(temp,O_RDONLY|O_DIRECT);
		unlink(temp);
	} else {
		char selected[512]="",op[32];
		unsigned long long offset;
		unsigned bytes;
		log=fopen(argv[1],"r");
		if(!log) fail("iolog");
		while(fgets(line,sizeof(line),log)) {
			if(sscanf(line,"%511s %31s %llu %u",device,op,&offset,&bytes)!=4) continue;
			if(strcmp(op,"read") || bytes!=BYTES || n==COUNT) return 2;
			if(*selected && strcmp(selected,device)) return 2;
			strcpy(selected,device);
			offsets[n++]=offset;
		}
		fclose(log);
		if(n!=COUNT) return 2;
		fd=open(selected,O_RDONLY|O_DIRECT|O_EXCL);
	}
	if(fd<0) fail("open");
	memset(data,0,COUNT*BYTES);
	pass(fd,offsets,depth);
	close(fd);
	free(data);
	return 0;
}
