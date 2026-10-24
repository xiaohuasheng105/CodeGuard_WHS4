/*
 * lab-init: 실험용 컨테이너 PID 1
 *
 * CodeGuard의 strace + codeguard-init 구조에서 측정과 관련된 부분만 남긴 것이다.
 *   1. 자식 하나를 fork한다. 자식은 /gate/start.ready 파일이 생길 때까지 기다린다.
 *      (호스트 하네스는 이 대기 중인 자식의 TID를 eBPF 측정기에 Root TID로 등록한다.)
 *   2. 시작 파일이 생기면 자식은 같은 TID에서 사용자 프로그램으로 execv 한다.
 *   3. PID 1은 모든 자손이 끝날 때까지 회수(reap)한 뒤,
 *      컨테이너 cgroup의 pids.peak, memory.peak, cpu.stat 값을 /gate/result.txt에 기록한다.
 *
 * 컨테이너 안의 CLOCK_MONOTONIC은 호스트와 같은 기준이므로(time namespace 미사용)
 * 여기서 기록한 시각은 eBPF의 bpf_ktime_get_ns() 및 호스트 하네스 시각과 직접 비교할 수 있다.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define GATE_DIR "/gate"
#define START_READY GATE_DIR "/start.ready"
#define RESULT_PATH GATE_DIR "/result.txt"
#define START_WAIT_SECONDS 30

static unsigned long long now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long long)ts.tv_sec * 1000000000ULL + (unsigned long long)ts.tv_nsec;
}

static int wait_for_start_file(void)
{
    unsigned long long deadline = now_ns() + START_WAIT_SECONDS * 1000000000ULL;
    struct timespec pause_time = { .tv_sec = 0, .tv_nsec = 1000000 }; /* 1ms */
    struct stat marker;

    for (;;) {
        if (lstat(START_READY, &marker) == 0)
            return S_ISREG(marker.st_mode) ? 0 : -1;
        if (errno != ENOENT)
            return -1;
        if (now_ns() >= deadline) {
            errno = ETIMEDOUT;
            return -1;
        }
        nanosleep(&pause_time, NULL);
    }
}

static long long read_single_value(const char *path)
{
    FILE *file = fopen(path, "r");
    long long value = -1;

    if (!file)
        return -1;
    if (fscanf(file, "%lld", &value) != 1)
        value = -1;
    fclose(file);
    return value;
}

static long long read_keyed_value(const char *path, const char *key)
{
    FILE *file = fopen(path, "r");
    char name[64];
    long long value;
    long long found = -1;

    if (!file)
        return -1;
    while (fscanf(file, "%63s %lld", name, &value) == 2) {
        if (strcmp(name, key) == 0) {
            found = value;
            break;
        }
    }
    fclose(file);
    return found;
}

int main(int argc, char **argv)
{
    int index = 1;
    pid_t root;
    int root_status = -1;
    unsigned long long lineage_end_ns;
    FILE *result;

    if (argc < 3 || strcmp(argv[1], "--") != 0) {
        fprintf(stderr, "usage: %s -- PROGRAM [ARG ...]\n", argv[0]);
        return 2;
    }
    index = 2;

    root = fork();
    if (root < 0) {
        perror("lab-init fork");
        return 3;
    }
    if (root == 0) {
        if (wait_for_start_file() < 0) {
            perror("lab-init start gate");
            _exit(125);
        }
        execv(argv[index], &argv[index]);
        perror("lab-init execv");
        _exit(127);
    }

    for (;;) {
        int status;
        pid_t done = waitpid(-1, &status, 0);

        if (done < 0) {
            if (errno == EINTR)
                continue;
            break; /* ECHILD: 사용자 계보가 모두 종료됨 */
        }
        if (done == root)
            root_status = status;
    }
    lineage_end_ns = now_ns();

    result = fopen(RESULT_PATH, "w");
    if (!result)
        return 4;
    fprintf(result, "root_wait_status %d\n", root_status);
    fprintf(result, "init_lineage_end_ns %llu\n", lineage_end_ns);
    fprintf(result, "cg_pids_peak %lld\n", read_single_value("/sys/fs/cgroup/pids.peak"));
    fprintf(result, "cg_memory_peak %lld\n", read_single_value("/sys/fs/cgroup/memory.peak"));
    fprintf(result, "cg_cpu_usage_usec %lld\n",
            read_keyed_value("/sys/fs/cgroup/cpu.stat", "usage_usec"));
    fprintf(result, "cg_pids_events_max %lld\n",
            read_keyed_value("/sys/fs/cgroup/pids.events", "max"));
    fclose(result);
    return 0;
}
