# ebpf-lab: CodeGuard eBPF 측정 실험용 최소 구성

CodeGuard에서 **사용자 코드 실행 측정**에 필요한 부분만 떼어 낸 실험 환경이다.
백엔드·DB·프론트엔드, 그리고 측정과 무관한 보안 기능(Landlock 파일 제한, 네트워크 제한, strace 추적)은 넣지 않았다.

## 무엇을 가져왔고 무엇을 뺐나

| 구성 요소 | 출처 | 처리 |
|---|---|---|
| eBPF 커널 프로그램 `task_tracker.bpf.c` | `runner/native/task_tracker/` | 그대로 복사 |
| 측정기 데몬 `task_trackerd.c`, `task_tracker_shared.h`, systemd unit | 같은 곳 | 그대로 복사 |
| 측정기 클라이언트 `lab/tracker_client.py` | `runner/metrics/task_tracker.py` | 오류 플래그를 예외 대신 값으로 돌려주도록 단순화 |
| 시작 동기화 `container/lab_init.c` | `codeguard_init.c` + `start_gate.py` | 시작 파일 대기 → 같은 TID에서 exec 하는 핵심만 남김. 권한 검증·Landlock 제거 |
| 컨테이너 PID 1 | CodeGuard는 `strace` | `lab-init`이 자손을 회수하고 cgroup 값을 기록 |
| Runner 실행 흐름 | `pipeline/execution.py` (약 1,100줄) | `lab/harness.py` 한 함수로 재구성 |
| 테스트 프로그램 | `tests/integration/...` | 인자로 조건을 바꿀 수 있는 워크로드 7개로 재작성 |

측정 원리(시작 전 Root TID 등록 → exec 시각 기록 → 사용자 계보 Task 집계 → 마지막 Task 종료 시각 기록)는 CodeGuard와 같다.
다만 실제 서비스는 strace가 사용자 코드를 추적하므로 실행 시간이 더 길다. 논문에는 "측정 구조를 분리 구현한 실험용 하네스"로 적는다.

## 폴더 구조

```
ebpf-lab/
├── setup.sh               # 환경 준비 (측정기 확인 → 이미지 빌드 → venv → smoke 테스트)
├── native/                # eBPF 측정기 소스 (이미 설치되어 있으면 빌드하지 않음)
├── container/
│   ├── Dockerfile         # gcc:15.2.0 + lab-init + 워크로드
│   └── lab_init.c         # 실험용 PID 1 (시작 동기화)
├── workloads/             # 실험용 C 프로그램
│   ├── busy.c  sleeper.c  # E1: 정해진 시간 동안 CPU 사용 / 잠들기
│   ├── threads.c forks.c  # E2·E3·E4: N개 Task를 동시에 유지
│   ├── leader_exit.c      # E4: 메인 스레드가 먼저 종료
│   ├── forkloop.c         # E5: fork/exit 반복 마이크로벤치마크
│   └── memspike.c         # E6: 짧은 메모리 급증
├── lab/
│   ├── harness.py         # 실행 1회 = 모든 측정 방식을 동시에 기록
│   ├── experiments.py     # E1~E6 실행
│   └── analyze.py         # CSV → 요약 표
└── results/               # 실험 결과 CSV (자동 생성)
```

## 실행 순서

```bash
cd ebpf-lab
bash setup.sh                       # 마지막에 smoke 결과가 출력되면 준비 완료

.venv/bin/python lab/experiments.py e1 --reps 30   # 약 20~30분
.venv/bin/python lab/experiments.py e2 --reps 50
.venv/bin/python lab/experiments.py e3 --reps 30
.venv/bin/python lab/experiments.py e4 --reps 30
.venv/bin/python lab/experiments.py e6 --reps 30

# E5는 세 번에 나눠 실행한다
.venv/bin/python lab/experiments.py e5 --mode registered   --reps 20
.venv/bin/python lab/experiments.py e5 --mode unregistered --reps 20
sudo systemctl stop codeguard-task-tracker
.venv/bin/python lab/experiments.py e5 --mode detached     --reps 20
sudo systemctl start codeguard-task-tracker

.venv/bin/python lab/analyze.py results/*.csv > results/summary.md
```

처음에는 `--reps 3`으로 짧게 돌려서 오류가 없는지 먼저 확인한다.

## smoke 결과 읽는 법

`sleeper 200`(200ms 잠들기)을 한 번 실행한 결과다. 정상이면 대략 다음과 같다.

| 항목 | 기대값 |
|---|---|
| `wall_ebpf_ms` | 200을 조금 넘음 |
| `wall_gate_ms` | eBPF보다 수십~수백 ms 큼 (컨테이너 종료 시간 포함) |
| `wall_container_ms` | 가장 큼 (컨테이너 시작 시간까지 포함) |
| `user_task_peak / process_at_peak / thread_at_peak` | 1 / 1 / 0 |
| `cg_pids_peak` | 2 이상 (lab-init 포함) |
| `tracker_error`, `tracker_error_flags` | 비어 있음 / 0 |

## 실험별 기록 항목

| 실험 | 비교하는 값 |
|---|---|
| E1 | `wall_container_ms`, `wall_gate_ms`, `wall_ebpf_ms`, `wall_self_ms` 와 목표 시간 |
| E2 | `cg_pids_peak`, `poll_pids_100ms`, `user_task_peak` 의 반복 분포 |
| E3 | `poll_pids_{10,50,100}ms`, `cg_pids_peak`, `user_task_peak` 가 동시 Task 최댓값을 잡았는지 |
| E4 | 경계 사례별 user/process/thread 값, pids 제한 동작, 준비 지연 제외 여부, 동시 실행 격리 |
| E5 | `wall_self_ms` (측정기 등록 / 미등록 / 정지) × 동시 실행 1·2·4 |
| E6 | `poll_mem_{50,100}ms` / `cg_memory_peak` |

## 주의

- 측정기 소켓(`/run/codeguard/task-tracker.sock`)은 `codeguard` 그룹만 쓸 수 있다. `groups`에 `codeguard`와 `docker`가 있어야 한다.
- 실험 중에는 다른 프로그램을 꺼 두고, Windows 전원 모드를 "최고 성능"으로 둔다.
- 컨테이너 안과 호스트, eBPF가 모두 `CLOCK_MONOTONIC`을 쓰므로 시각을 직접 빼서 비교할 수 있다.
