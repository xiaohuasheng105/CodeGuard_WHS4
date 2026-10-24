/*
 * forkloop N : fork 후 바로 종료·회수하는 과정을 N번 반복하고 걸린 시간을 보고한다.
 *   eBPF tracepoint(sched_process_fork/exit)가 붙어 있을 때의 비용을 재는 마이크로벤치마크. (E5)
 */
#include "lab_common.h"
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    long n = lab_arg(argc, argv, 1, 2000);
    unsigned long long t0 = lab_now_ns();

    for (long i = 0; i < n; i++) {
        pid_t pid = fork();
        if (pid < 0)
            return 1;
        if (pid == 0)
            _exit(0);
        if (waitpid(pid, NULL, 0) < 0)
            return 2;
    }
    lab_report(t0, lab_now_ns());
    return 0;
}
