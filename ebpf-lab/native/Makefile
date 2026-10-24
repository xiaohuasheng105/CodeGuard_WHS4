# eBPF Task tracker 데몬만 빌드한다.
# (CodeGuard runner/native/task_tracker/Makefile에서 codeguard-init 등 측정과 무관한 대상을 뺐다.)
CLANG ?= clang
CC ?= cc
BPFTOOL ?= bpftool

CFLAGS := -O2 -g -Wall -Wextra -Werror
BPF_CFLAGS := -O2 -g -target bpf -D__TARGET_ARCH_x86 -D__BPF__ \
	-I. -I/usr/include/$(shell uname -m)-linux-gnu
LIBBPF_FLAGS := $(shell pkg-config --cflags --libs libbpf)

.PHONY: all clean

all: codeguard-task-tracker

vmlinux.h:
	$(BPFTOOL) btf dump file /sys/kernel/btf/vmlinux format c > $@

task_tracker.bpf.o: task_tracker.bpf.c task_tracker_shared.h vmlinux.h
	$(CLANG) $(BPF_CFLAGS) -c $< -o $@

task_tracker.skel.h: task_tracker.bpf.o
	$(BPFTOOL) gen skeleton $< > $@

codeguard-task-tracker: task_trackerd.c task_tracker_shared.h task_tracker.skel.h
	$(CC) $(CFLAGS) -I. task_trackerd.c -o $@ $(LIBBPF_FLAGS)

clean:
	rm -f vmlinux.h task_tracker.bpf.o task_tracker.skel.h codeguard-task-tracker
