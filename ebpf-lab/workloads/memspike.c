/*
 * memspike MB HOLD_MS PRE_MS
 *   PRE_MS 기다린 뒤 MB 메가바이트를 할당하고 모든 페이지를 실제로 사용(touch)한다.
 *   HOLD_MS 동안 유지한 뒤 해제하고, 300ms 더 기다렸다가 끝난다. (E6 메모리 Peak)
 */
#include "lab_common.h"
#include <string.h>
#include <sys/mman.h>

int main(int argc, char **argv)
{
    long mb = lab_arg(argc, argv, 1, 64);
    long hold_ms = lab_arg(argc, argv, 2, 50);
    long pre_ms = lab_arg(argc, argv, 3, 0);
    size_t size = (size_t)mb * 1024 * 1024;
    unsigned long long t0 = lab_now_ns();
    char *block;

    lab_sleep_ns((unsigned long long)pre_ms * 1000000ULL);
    block = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (block == MAP_FAILED)
        return 1;
    memset(block, 1, size);
    lab_sleep_ns((unsigned long long)hold_ms * 1000000ULL);
    munmap(block, size);
    lab_sleep_ns(300000000ULL);
    lab_report(t0, lab_now_ns());
    return 0;
}
