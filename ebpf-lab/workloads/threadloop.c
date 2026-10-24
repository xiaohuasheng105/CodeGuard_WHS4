/*
 * threadloop N : 스레드를 만들고 바로 합류(join)하는 과정을 N번 반복하고 걸린 시간을 보고한다.
 *   sched_process_fork/exit tracepoint가 스레드 생성·종료마다 실행되는 비용을 잰다. (E5)
 */
#include "lab_common.h"
#include <pthread.h>

static void *worker(void *unused)
{
    (void)unused;
    return NULL;
}

int main(int argc, char **argv)
{
    long n = lab_arg(argc, argv, 1, 5000);
    unsigned long long t0 = lab_now_ns();

    for (long i = 0; i < n; i++) {
        pthread_t thread;
        if (pthread_create(&thread, NULL, worker, NULL) != 0)
            return 1;
        pthread_join(thread, NULL);
    }
    lab_report(t0, lab_now_ns());
    return 0;
}
