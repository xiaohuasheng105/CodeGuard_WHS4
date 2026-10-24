"""논문 실험 E1~E6 실행 스크립트.

사용법 (ebpf-lab 폴더에서):
    .venv/bin/python lab/experiments.py e1 --reps 30
    .venv/bin/python lab/experiments.py e5 --mode registered --reps 20
결과는 results/<실험>_<시각>.csv 로 저장된다. 조건 순서는 매번 무작위로 섞는다(시간에 따른 잡음 분산).
"""

from __future__ import annotations

import argparse
import csv
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import docker

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import RunConfig, run_once  # noqa: E402
from tracker_client import TrackerClient  # noqa: E402

RESULTS = Path(__file__).resolve().parent.parent / "results"


# ---------------------------------------------------------------- 공통 도구

def save(name: str, rows: list[dict]) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / f"{name}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n저장: {path} ({len(rows)}행)")
    return path


def run_trials(experiment: str, trials: list[tuple[dict, RunConfig]]) -> list[dict]:
    random.shuffle(trials)
    rows = []
    client = docker.from_env()
    tracker = TrackerClient()
    started = time.monotonic()
    for i, (meta, cfg) in enumerate(trials, 1):
        try:
            row = run_once(cfg, client, tracker)
        except Exception as exc:  # 한 번의 실패로 전체 실험을 멈추지 않는다
            row = {"harness_error": repr(exc)}
        row = {"experiment": experiment, **meta, **row}
        rows.append(row)
        elapsed = time.monotonic() - started
        print(f"\r[{experiment}] {i}/{len(trials)}  경과 {elapsed:5.0f}s", end="", flush=True)
    client.close()
    return rows


# ---------------------------------------------------------------- E1 실행 시간·판정 정확도

def e1(reps: int) -> list[dict]:
    trials = []
    for workload in ("busy", "sleeper"):
        for target in (10, 100, 1000, 5000):
            for rep in range(reps):
                trials.append(({"part": "accuracy", "target_ms": target, "rep": rep},
                               RunConfig(workload, [str(target)])))
    for target in (900, 950, 1000, 1050, 1100):
        for rep in range(reps):
            trials.append(({"part": "boundary", "target_ms": target, "limit_ms": 1000, "rep": rep},
                           RunConfig("busy", [str(target)])))
    return run_trials("e1", trials)


# ---------------------------------------------------------------- E2 반복 일관성

E2_CASES = {
    "single": ("sleeper", ["200"], (1, 1, 0)),
    "threads63": ("threads", ["63", "200000", "0"], (64, 1, 63)),
    "forks31": ("forks", ["31", "200000", "0"], (32, 32, 0)),
}


def e2(reps: int) -> list[dict]:
    trials = []
    for case, (workload, args, expected) in E2_CASES.items():
        for rep in range(reps):
            trials.append(({"case": case, "expected_user_tasks": expected[0],
                            "expected_processes": expected[1], "expected_threads": expected[2],
                            "rep": rep},
                           RunConfig(workload, args, pids_poll_ms=(100,))))
    return run_trials("e2", trials)


# ---------------------------------------------------------------- E3 짧은 Task 포착률

def e3(reps: int, n: int = 8) -> list[dict]:
    trials = []
    for workload in ("threads", "forks"):
        for hold_us in (100, 1000, 5000, 10000, 50000):
            for rep in range(reps):
                pre_us = random.randint(0, 200000)  # 폴링 주기와의 위상을 무작위로
                trials.append(({"burst_tasks": n, "hold_us": hold_us, "pre_us": pre_us,
                                "truth_user_tasks": n + 1, "rep": rep},
                               RunConfig(workload, [str(n), str(hold_us), str(pre_us)],
                                         pids_poll_ms=(10, 50, 100))))
    return run_trials("e3", trials)


# ---------------------------------------------------------------- E4 정합성·경계 사례

def e4(reps: int) -> list[dict]:
    trials = []
    for rep in range(reps):
        trials.append(({"case": "leader_exit", "expected": "3/1/2", "rep": rep},
                       RunConfig("leader_exit", [])))
    for rep in range(max(reps // 3, 5)):
        trials.append(({"case": "pids_limit_32", "rep": rep},
                       RunConfig("threads", ["40", "200000", "0"], pids_limit=32)))
        trials.append(({"case": "gate_delay_500ms", "rep": rep},
                       RunConfig("sleeper", ["200"], gate_delay_ms=500)))
    rows = run_trials("e4", trials)

    # 동시 실행 격리: 8개를 동시에 돌려 run_id별 값이 섞이지 않는지 확인
    rounds = max(reps // 6, 5)
    for rnd in range(rounds):
        cases = [("single", RunConfig("sleeper", ["300"])),
                 ("threads15", RunConfig("threads", ["15", "200000", "0"]))] * 4

        def go(item):
            name, cfg = item
            client = docker.from_env()
            try:
                return {"experiment": "e4", "case": f"concurrent_{name}", "round": rnd,
                        **run_once(cfg, client)}
            except Exception as exc:
                return {"experiment": "e4", "case": f"concurrent_{name}", "round": rnd,
                        "harness_error": repr(exc)}
            finally:
                client.close()

        with ThreadPoolExecutor(max_workers=len(cases)) as pool:
            rows.extend(pool.map(go, cases))
        print(f"\r[e4] 동시 실행 {rnd + 1}/{rounds}", end="", flush=True)
    return rows


# ---------------------------------------------------------------- E5 오버헤드

def e5(reps: int, mode: str) -> list[dict]:
    """mode
    registered : 측정기 실행 중 + 이번 실행을 등록 (실제 서비스 상태)
    unregistered : 측정기 실행 중이지만 등록하지 않음 (추적 대상 아닌 프로세스의 부담)
    detached : 측정기 서비스를 멈춘 상태 (sudo systemctl stop codeguard-task-tracker)
    """
    use_tracker = mode == "registered"
    rows = []
    workloads = [("forkloop", ["2000"]), ("busy", ["1000"])]
    for concurrency in (1, 2, 4):
        for rep in range(reps):
            for workload, args in workloads:
                cfg = RunConfig(workload, args, use_tracker=use_tracker)

                def go(_):
                    client = docker.from_env()
                    try:
                        return run_once(cfg, client)
                    except Exception as exc:
                        return {"harness_error": repr(exc)}
                    finally:
                        client.close()

                with ThreadPoolExecutor(max_workers=concurrency) as pool:
                    batch = list(pool.map(go, range(concurrency)))
                for idx, row in enumerate(batch):
                    rows.append({"experiment": "e5", "mode": mode, "concurrency": concurrency,
                                 "rep": rep, "slot": idx, **row})
            print(f"\r[e5:{mode}] 동시 {concurrency}개, {rep + 1}/{reps}", end="", flush=True)
    return rows


# ---------------------------------------------------------------- E6 메모리 Peak

def e6(reps: int) -> list[dict]:
    trials = []
    for hold_ms in (10, 50, 100, 200, 500):
        for rep in range(reps):
            pre_ms = random.randint(0, 200)
            trials.append(({"spike_mb": 64, "hold_ms": hold_ms, "pre_ms": pre_ms, "rep": rep},
                           RunConfig("memspike", ["64", str(hold_ms), str(pre_ms)],
                                     memory_mb=256, mem_poll_ms=(50, 100))))
    return run_trials("e6", trials)


# ---------------------------------------------------------------- 실행

def main() -> None:
    parser = argparse.ArgumentParser(description="eBPF 측정 실험")
    parser.add_argument("experiment", choices=["smoke", "e1", "e2", "e3", "e4", "e5", "e6"])
    parser.add_argument("--reps", type=int, default=30)
    parser.add_argument("--mode", choices=["registered", "unregistered", "detached"],
                        default="registered", help="E5 전용")
    args = parser.parse_args()

    if args.experiment == "smoke":
        row = run_once(RunConfig("sleeper", ["200"], pids_poll_ms=(100,)))
        for key, value in row.items():
            print(f"{key:28s} {value}")
        return

    if args.experiment != "e5" or args.mode != "detached":
        TrackerClient().health()  # 측정기가 안 켜져 있으면 여기서 바로 실패한다

    func = {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e6": e6}.get(args.experiment)
    rows = e5(args.reps, args.mode) if args.experiment == "e5" else func(args.reps)
    name = f"e5_{args.mode}" if args.experiment == "e5" else args.experiment
    save(name, rows)


if __name__ == "__main__":
    main()
