/*
 * forks N HOLD_US PRE_US
 *   PRE_US 마이크로초 기다린 뒤, 자식 프로세스 N개를 만들어 HOLD_US 동안 동시에 존재하게 한다.
 *   모든 자식은 공유 파이프로 '출발 신호'를 받은 뒤 HOLD_US 동안 유지하고 종료한다.
 *   이후 300ms 더 기다렸다가 끝난다. 동시에 존재하는 Task 수의 참값 = N + 1. (E2, E3)
 */
#include "lab_common.h"
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    long n = lab_arg(argc, argv, 1, 8);
    long hold_us = lab_arg(argc, argv, 2, 200000);
    long pre_us = lab_arg(argc, argv, 3, 0);
    int go[2];
    long created = 0;
    unsigned long long t0 = lab_now_ns();

    lab_sleep_ns((unsigned long long)pre_us * 1000ULL);
    if (pipe(go) != 0)
        return 1;

    for (long i = 0; i < n; i++) {
        pid_t pid = fork();
        if (pid < 0)
            break;
        if (pid == 0) {
            char byte;
            close(go[1]);
            /* 부모가 쓰기 끝을 닫으면 read가 0을 반환하며 모든 자식이 동시에 출발한다. */
            while (read(go[0], &byte, 1) > 0) {
            }
            lab_sleep_ns((unsigned long long)hold_us * 1000ULL);
            _exit(0);
        }
        created++;
    }
    close(go[0]);
    close(go[1]);
    while (wait(NULL) > 0) {
    }
    lab_sleep_ns(300000000ULL);
    printf("LAB_CREATED=%ld\nLAB_FAILED=%ld\n", created, n - created);
    lab_report(t0, lab_now_ns());
    return created == n ? 0 : 3;
}
