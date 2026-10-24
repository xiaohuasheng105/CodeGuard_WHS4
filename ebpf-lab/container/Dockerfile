# 실험용 실행 이미지 (빌드 위치: ebpf-lab 폴더)
#   docker build -f container/Dockerfile -t codeguard-lab:dev .
# CodeGuard 실행 이미지와 같은 gcc 15.2.0 기반을 쓰되,
# 측정과 무관한 strace·Landlock·파일시스템 manifest는 넣지 않는다.
FROM gcc:15.2.0

COPY container/lab_init.c /src/lab_init.c
COPY workloads/ /src/workloads/

RUN mkdir -p /lab/bin /gate \
    && gcc -O2 -Wall -Wextra -o /lab/lab-init /src/lab_init.c \
    && for source in /src/workloads/*.c; do \
         name="$(basename "$source" .c)"; \
         gcc -O2 -Wall -Wextra -pthread -I/src/workloads -o "/lab/bin/$name" "$source" || exit 1; \
       done \
    && groupadd --gid 10001 codeguard \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin codeguard \
    && chmod 0555 /lab/lab-init /lab/bin/*

WORKDIR /lab
