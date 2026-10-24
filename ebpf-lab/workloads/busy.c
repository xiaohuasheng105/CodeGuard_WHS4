/* busy MS : MS 밀리초 동안 CPU를 사용한다. (E1 실행 시간 정확도, E5 오버헤드) */
#include "lab_common.h"

int main(int argc, char **argv)
{
    long ms = lab_arg(argc, argv, 1, 100);
    unsigned long long t0 = lab_now_ns();
    lab_busy_ns((unsigned long long)ms * 1000000ULL);
    lab_report(t0, lab_now_ns());
    return 0;
}
