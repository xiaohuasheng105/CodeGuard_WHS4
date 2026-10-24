/*
 * execloop N : fork 후 자식이 /bin/true를 exec 하고 종료하는 과정을 N번 반복한다.
 *   fork·exec·exit 세 tracepoint가 모두 실행되는 비용을 잰다. (E5)
 */
#include "lab_common.h"
#include <sys/wait.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    long n = lab_arg(argc, argv, 1, 1000);
    unsigned long long t0 = lab_now_ns();

    for (long i = 0; i < n; i++) {
        pid_t pid = fork();
        if (pid < 0)
            return 1;
        if (pid == 0) {
            execl("/bin/true", "true", (char *)NULL);
            _exit(127);
        }
        if (waitpid(pid, NULL, 0) < 0)
            return 2;
    }
    lab_report(t0, lab_now_ns());
    return 0;
}
