/*
 * leader_exit : 대표 Task(메인 스레드)가 먼저 종료되는 경계 사례 (E4)
 *   메인이 생존 스레드 1개를 만들고 pthread_exit 한다.
 *   생존 스레드는 100ms 뒤 스레드 2개를 더 만든다.
 *   기대값: user_task_peak = 3, process = 1, thread = 2
 */
#include "lab_common.h"
#include <pthread.h>

static void *leaf(void *unused)
{
    (void)unused;
    lab_sleep_ns(300000000ULL);
    return NULL;
}

static void *survivor(void *unused)
{
    pthread_t first, second;
    (void)unused;
    lab_sleep_ns(100000000ULL);
    if (pthread_create(&first, NULL, leaf, NULL) != 0)
        return (void *)1;
    if (pthread_create(&second, NULL, leaf, NULL) != 0)
        return (void *)2;
    pthread_join(first, NULL);
    pthread_join(second, NULL);
    return NULL;
}

int main(void)
{
    pthread_t worker;
    if (pthread_create(&worker, NULL, survivor, NULL) != 0)
        return 1;
    pthread_exit(NULL);
}
