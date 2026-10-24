"""실험 결과 CSV를 요약해 표(마크다운)로 출력한다.

사용법: .venv/bin/python lab/analyze.py results/e1_*.csv results/e2_*.csv ...
여러 파일을 한꺼번에 넘기면 실험 종류별로 나눠 요약한다.
"""

from __future__ import annotations

import csv
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def num(value):
    try:
        return float(value) if value not in ("", None) else None
    except ValueError:
        return None


def summary(values: list[float]) -> str:
    values = [v for v in values if v is not None]
    if not values:
        return "n=0"
    n = len(values)
    mean = statistics.fmean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    ci = 1.96 * sd / math.sqrt(n) if n > 1 else 0.0
    return f"{mean:.2f} ± {sd:.2f} (95%CI ±{ci:.2f}, n={n})"


def load(paths: list[str]) -> dict[str, list[dict]]:
    by_exp: dict[str, list[dict]] = defaultdict(list)
    for path in paths:
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                by_exp[row.get("experiment", Path(path).stem)].append(row)
    return by_exp


def errors(rows: list[dict]) -> None:
    harness = sum(1 for r in rows if r.get("harness_error"))
    tracker = sum(1 for r in rows if r.get("tracker_error"))
    flags = sum(1 for r in rows if num(r.get("tracker_error_flags")) not in (None, 0.0))
    violations = sum(
        1 for r in rows
        if num(r.get("cg_pids_peak")) is not None and num(r.get("user_task_peak")) is not None
        and num(r["cg_pids_peak"]) < num(r["user_task_peak"])
    )
    print(f"- 실행 수 {len(rows)}, 하네스 오류 {harness}, 측정기 통신 오류 {tracker}, "
          f"eBPF 오류 플래그 {flags}, `pids_peak < user_task_peak` 위반 {violations}")


METHODS = [("wall_container_ms", "컨테이너 단위"), ("wall_gate_ms", "Gate 기준(legacy)"),
           ("wall_ebpf_ms", "eBPF"), ("wall_self_ms", "자기 보고")]


def e1(rows: list[dict]) -> None:
    print("\n## E1 실행 시간 정확도 (측정값 − 목표 시간, ms)\n")
    groups = defaultdict(list)
    for r in rows:
        if r.get("part") == "accuracy":
            groups[(r["workload"], int(r["target_ms"]))].append(r)
    print("| 워크로드 | 목표 | " + " | ".join(m[1] for m in METHODS) + " |")
    print("|---|---|" + "---|" * len(METHODS))
    for (workload, target), rs in sorted(groups.items()):
        cells = [summary([num(r.get(k)) - target for r in rs if num(r.get(k)) is not None])
                 for k, _ in METHODS]
        print(f"| {workload} | {target} | " + " | ".join(cells) + " |")

    print("\n## E1 제한 1000ms 경계 판정 (초과로 판정한 비율)\n")
    groups = defaultdict(list)
    for r in rows:
        if r.get("part") == "boundary":
            groups[int(r["target_ms"])].append(r)
    print("| 목표 | 참 판정 | " + " | ".join(m[1] for m in METHODS) + " |")
    print("|---|---|" + "---|" * len(METHODS))
    wrong = Counter()
    total = Counter()
    for target, rs in sorted(groups.items()):
        truth = target > 1000
        cells = []
        for key, label in METHODS:
            vals = [num(r.get(key)) for r in rs if num(r.get(key)) is not None]
            over = sum(1 for v in vals if v > 1000)
            cells.append(f"{over}/{len(vals)}")
            if target != 1000:
                wrong[label] += sum(1 for v in vals if (v > 1000) != truth)
                total[label] += len(vals)
        print(f"| {target} | {'초과' if truth else '정상'} | " + " | ".join(cells) + " |")
    print("\n오판정률(목표 1000ms 제외): " + ", ".join(
        f"{label} {wrong[label]}/{total[label]}" for _, label in METHODS if total[label]))


def e2(rows: list[dict]) -> None:
    print("\n## E2 반복 일관성 (값의 분포)\n")
    print("| 사례 | 지표 | 평균±표준편차 | 서로 다른 값 | 최빈값 비율 |")
    print("|---|---|---|---|---|")
    groups = defaultdict(list)
    for r in rows:
        groups[r["case"]].append(r)
    for case, rs in groups.items():
        for key in ("cg_pids_peak", "poll_pids_100ms", "user_task_peak",
                    "process_at_peak", "thread_at_peak"):
            vals = [num(r.get(key)) for r in rs if num(r.get(key)) is not None]
            if not vals:
                continue
            counts = Counter(vals)
            mode_share = counts.most_common(1)[0][1] / len(vals)
            print(f"| {case} | {key} | {summary(vals)} | "
                  f"{sorted(int(v) for v in counts)} | {mode_share:.0%} |")


def e3(rows: list[dict]) -> None:
    print("\n## E3 짧은 Task 포착률 (동시 Task 최댓값을 정확히 잡은 비율)\n")
    print("cgroup 기반 값은 lab-init(PID 1)을 포함하므로 참값을 N+2로, eBPF는 N+1로 본다.\n")
    keys = [("poll_pids_10ms", 2), ("poll_pids_50ms", 2), ("poll_pids_100ms", 2),
            ("cg_pids_peak", 2), ("user_task_peak", 1)]
    print("| 워크로드 | 유지 시간(µs) | " + " | ".join(k for k, _ in keys) + " |")
    print("|---|---|" + "---|" * len(keys))
    groups = defaultdict(list)
    for r in rows:
        groups[(r["workload"], int(r["hold_us"]))].append(r)
    for (workload, hold), rs in sorted(groups.items()):
        n = int(rs[0]["burst_tasks"])
        cells = []
        for key, extra in keys:
            vals = [num(r.get(key)) for r in rs if num(r.get(key)) is not None]
            hit = sum(1 for v in vals if v >= n + extra)
            cells.append(f"{hit}/{len(vals)}")
        print(f"| {workload} | {hold} | " + " | ".join(cells) + " |")


def e4(rows: list[dict]) -> None:
    print("\n## E4 정합성·경계 사례\n")
    groups = defaultdict(list)
    for r in rows:
        groups[r["case"]].append(r)
    for case, rs in groups.items():
        triple = Counter((r.get("user_task_peak"), r.get("process_at_peak"), r.get("thread_at_peak"))
                         for r in rs)
        print(f"- **{case}** (n={len(rs)}): user/process/thread 분포 {dict(triple)}")
        if case == "pids_limit_32":
            print(f"  - cg_pids_peak {summary([num(r.get('cg_pids_peak')) for r in rs])}, "
                  f"pids.events max>0 비율 "
                  f"{sum(1 for r in rs if (num(r.get('cg_pids_events_max')) or 0) > 0)}/{len(rs)}, "
                  f"생성 실패 수 {summary([num(r.get('lab_failed')) for r in rs])}")
        if case == "gate_delay_500ms":
            for key, label in METHODS:
                print(f"  - {label}: {summary([num(r.get(key)) for r in rs])}")


def e5(rows: list[dict]) -> None:
    print("\n## E5 오버헤드 (워크로드 자기 보고 시간, ms)\n")
    groups = defaultdict(list)
    for r in rows:
        if not r.get("harness_error"):
            groups[(r["workload"], int(r["concurrency"]), r["mode"])].append(num(r.get("wall_self_ms")))
    base = {(w, c): statistics.fmean([v for v in vals if v is not None])
            for (w, c, m), vals in groups.items() if m == "detached" and any(vals)}
    print("| 워크로드 | 동시 실행 | 모드 | 시간 | detached 대비 |")
    print("|---|---|---|---|---|")
    for (w, c, m), vals in sorted(groups.items()):
        vals = [v for v in vals if v is not None]
        rel = ""
        if (w, c) in base and vals:
            rel = f"{(statistics.fmean(vals) / base[(w, c)] - 1) * 100:+.1f}%"
        print(f"| {w} | {c} | {m} | {summary(vals)} | {rel} |")


def e6(rows: list[dict]) -> None:
    print("\n## E6 메모리 Peak (폴링 최댓값 / memory.peak)\n")
    print("| 유지 시간(ms) | 50ms 폴링 비율 | 100ms 폴링 비율 | 90% 이상 포착(50/100ms) |")
    print("|---|---|---|---|")
    groups = defaultdict(list)
    for r in rows:
        groups[int(r["hold_ms"])].append(r)
    for hold, rs in sorted(groups.items()):
        cells, hits = [], []
        for key in ("poll_mem_50ms", "poll_mem_100ms"):
            ratios = [num(r.get(key)) / num(r["cg_memory_peak"]) for r in rs
                      if num(r.get(key)) and num(r.get("cg_memory_peak"))]
            cells.append(summary(ratios))
            hits.append(f"{sum(1 for x in ratios if x >= 0.9)}/{len(ratios)}")
        print(f"| {hold} | {cells[0]} | {cells[1]} | {' / '.join(hits)} |")


def main() -> None:
    by_exp = load(sys.argv[1:])
    handlers = {"e1": e1, "e2": e2, "e3": e3, "e4": e4, "e5": e5, "e6": e6}
    for exp, rows in sorted(by_exp.items()):
        print(f"\n# {exp}")
        errors(rows)
        handlers.get(exp, lambda _: None)(rows)


if __name__ == "__main__":
    main()
