/* 모든 워크로드가 공유하는 도구: 시각 측정과 결과 출력 */
#ifndef LAB_COMMON_H
#define LAB_COMMON_H

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static inline unsigned long long lab_now_ns(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (unsigned long long)ts.tv_sec * 1000000000ULL + (unsigned long long)ts.tv_nsec;
}

/* 지정한 시간(나노초)만큼 CPU를 사용하며 기다린다. */
static inline void lab_busy_ns(unsigned long long duration_ns)
{
    unsigned long long end = lab_now_ns() + duration_ns;
    volatile unsigned long long sink = 0;
    while (lab_now_ns() < end)
        sink++;
}

/* 지정한 시간(나노초)만큼 잠든다. */
static inline void lab_sleep_ns(unsigned long long duration_ns)
{
    struct timespec ts = {
        .tv_sec = (time_t)(duration_ns / 1000000000ULL),
        .tv_nsec = (long)(duration_ns % 1000000000ULL),
    };
    while (nanosleep(&ts, &ts) != 0) {
    }
}

/* main 시작·종료 시각을 출력한다. 하네스가 stdout에서 읽어 '자기 보고 시간'으로 쓴다. */
static inline void lab_report(unsigned long long t0, unsigned long long t1)
{
    printf("LAB_T0=%llu\nLAB_T1=%llu\n", t0, t1);
    fflush(stdout);
}

static inline long lab_arg(int argc, char **argv, int index, long fallback)
{
    return argc > index ? strtol(argv[index], NULL, 10) : fallback;
}

#endif
