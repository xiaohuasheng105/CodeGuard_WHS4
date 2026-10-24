/*
 * threads N HOLD_US PRE_US
 *   PRE_US 마이크로초 기다린 뒤, 스레드 N개를 만들어 장벽(barrier)에서 동시에 존재하게 하고
 *   HOLD_US 마이크로초 유지한 뒤 모두 종료한다. 이후 300ms 더 기다렸다가 끝난다.
 *   동시에 존재하는 Task 수의 참값 = N + 1 (메인 스레드 포함)
 *   pthread_create 실패 수를 출력한다. (E2, E3, E4)
 */
#include "lab_common.h"
#include <pthread.h>
#include <unistd.h>

static pthread_barrier_t barrier;
static unsigned long long hold_ns;

static void *worker(void *unused)
{
    (void)unused;
    pthread_barrier_wait(&barrier);
    lab_sleep_ns(hold_ns);
    return NULL;
}

int main(int argc, char **argv)
{
    long n = lab_arg(argc, argv, 1, 8);
    long hold_us = lab_arg(argc, argv, 2, 200000);
    long pre_us = lab_arg(argc, argv, 3, 0);
    pthread_t *threads = calloc((size_t)n, sizeof(*threads));
    long created = 0;
    unsigned long long t0 = lab_now_ns();

    hold_ns = (unsigned long long)hold_us * 1000ULL;
    lab_sleep_ns((unsigned long long)pre_us * 1000ULL);

    /* 모든 스레드와 메인이 장벽에 도착해야 동시에 출발한다.
       생성이 하나라도 실패하면 장벽이 풀리지 않으므로 실패 수만 기록하고 종료한다. */
    pthread_barrier_init(&barrier, NULL, (unsigned)(n + 1));
    for (long i = 0; i < n; i++) {
        if (pthread_create(&threads[i], NULL, worker, NULL) == 0)
            created++;
        else
            break;
    }
    if (created == n) {
        pthread_barrier_wait(&barrier);
        lab_sleep_ns(hold_ns);
    }
    if (created == n) {
        for (long i = 0; i < n; i++)
            pthread_join(threads[i], NULL);
    }
    lab_sleep_ns(300000000ULL);
    printf("LAB_CREATED=%ld\nLAB_FAILED=%ld\n", created, n - created);
    lab_report(t0, lab_now_ns());
    if (created != n)
        _exit(3);
    return 0;
}
