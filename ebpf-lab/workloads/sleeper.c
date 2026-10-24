/* sleeper MS : MS 밀리초 동안 잠든다. (E1 실행 시간 정확도, E2 단일 프로세스) */
#include "lab_common.h"

int main(int argc, char **argv)
{
    long ms = lab_arg(argc, argv, 1, 100);
    unsigned long long t0 = lab_now_ns();
    lab_sleep_ns((unsigned long long)ms * 1000000ULL);
    lab_report(t0, lab_now_ns());
    return 0;
}
