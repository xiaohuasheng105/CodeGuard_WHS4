"""실행 1회를 수행하고 모든 측정 방식의 값을 한 번에 기록하는 하네스.

한 번의 실행에서 다음 값을 함께 기록하므로, 같은 실행을 여러 방식으로 잰 결과를 직접 비교할 수 있다.

  실행 시간
    wall_container_ms : 컨테이너 시작 요청 ~ 컨테이너 종료 확인 (컨테이너 단위 측정, 단순 방식)
    wall_gate_ms      : 시작 파일 생성 ~ 컨테이너 종료 확인 (CodeGuard legacy 방식)
    wall_ebpf_ms      : 사용자 프로그램 exec ~ 사용자 계보 마지막 Task 종료 (eBPF 방식)
    wall_self_ms      : 워크로드가 main 안에서 스스로 잰 시간 (참고용 기준값)

  Task 수
    cg_pids_peak      : 컨테이너 cgroup 전체의 pids.peak (커널 기록, 컨테이너 Task 포함)
    poll_pids_<N>ms   : pids.current를 N ms 간격으로 읽은 최댓값 (폴링 방식)
    user_task_peak    : eBPF가 집계한 사용자 계보 Task 최댓값 (+ 프로세스/스레드 구성)

  메모리
    cg_memory_peak    : 커널 memory.peak
    poll_mem_<N>ms    : memory.current를 N ms 간격으로 읽은 최댓값

모든 시각은 CLOCK_MONOTONIC(나노초) 기준이다. 컨테이너 안·호스트·eBPF가 같은 시계를 쓴다.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import docker

from tracker_client import TrackerClient, TrackerError, cgroup_id_of, cgroup_path_of

IMAGE = os.environ.get("LAB_IMAGE", "codeguard-lab:dev")
GATE_ROOT = Path(os.environ.get("LAB_GATE_ROOT", "/tmp/codeguard-lab"))


@dataclass
class RunConfig:
    workload: str                     # /lab/bin 아래 워크로드 이름 (busy, sleeper, threads ...)
    args: list[str] = field(default_factory=list)
    memory_mb: int = 256
    pids_limit: int = 128
    cpus: float = 1.0
    use_tracker: bool = True          # False면 등록하지 않음 (eBPF 프로그램은 붙어 있음)
    pids_poll_ms: tuple[int, ...] = ()
    mem_poll_ms: tuple[int, ...] = ()
    gate_delay_ms: int = 0            # 시작 파일 생성 전 일부러 기다리는 시간 (준비 지연 모의)
    timeout_s: float = 60.0


class _Poller(threading.Thread):
    """cgroup 파일 하나를 일정 간격으로 읽어 최댓값을 기록한다."""

    def __init__(self, path: Path, interval_ms: int) -> None:
        super().__init__(daemon=True)
        self.path = path
        self.interval_ns = interval_ms * 1_000_000
        self.stop_event = threading.Event()
        self.max_value: int | None = None
        self.samples = 0

    def run(self) -> None:
        next_at = time.monotonic_ns()
        while not self.stop_event.is_set():
            try:
                value = int(self.path.read_text().split()[0])
                self.samples += 1
                if self.max_value is None or value > self.max_value:
                    self.max_value = value
            except (OSError, ValueError, IndexError):
                pass  # 컨테이너 종료 후 cgroup이 사라지면 읽기에 실패한다
            next_at += self.interval_ns
            delay = next_at - time.monotonic_ns()
            if delay > 0:
                self.stop_event.wait(delay / 1e9)


def _find_root_tid(pid1: int, timeout_s: float = 3.0) -> int:
    """lab-init(PID 1)이 fork한, 시작 파일을 기다리는 자식의 호스트 TID를 찾는다."""
    deadline = time.monotonic() + timeout_s
    children_file = Path(f"/proc/{pid1}/task/{pid1}/children")
    while time.monotonic() < deadline:
        try:
            children = children_file.read_text().split()
            if children:
                return int(children[0])
        except OSError:
            pass
        time.sleep(0.001)
    raise RuntimeError("waiting root task was not found")


def _parse_key_values(text: str, sep: str) -> dict[str, str]:
    values = {}
    for line in text.splitlines():
        if sep in line:
            key, value = line.split(sep, 1)
            values[key.strip()] = value.strip()
    return values


def run_once(cfg: RunConfig, client: docker.DockerClient | None = None,
             tracker: TrackerClient | None = None) -> dict:
    own_client = client is None
    client = client or docker.from_env()
    tracker = tracker or TrackerClient()
    run_id = uuid4()
    GATE_ROOT.mkdir(parents=True, exist_ok=True)
    gate = Path(tempfile.mkdtemp(prefix="run-", dir=GATE_ROOT))
    gate.chmod(0o777)

    row: dict = {
        "run_id": str(run_id), "workload": cfg.workload, "args": " ".join(cfg.args),
        "pids_limit": cfg.pids_limit, "memory_mb": cfg.memory_mb, "cpus": cfg.cpus,
        "use_tracker": cfg.use_tracker, "gate_delay_ms": cfg.gate_delay_ms,
    }
    pollers: dict[str, _Poller] = {}
    container = None
    try:
        container = client.containers.create(
            IMAGE,
            command=["/lab/lab-init", "--", f"/lab/bin/{cfg.workload}", *cfg.args],
            user="10001:10001",
            mem_limit=f"{cfg.memory_mb}m",
            memswap_limit=f"{cfg.memory_mb}m",
            pids_limit=cfg.pids_limit,
            nano_cpus=int(cfg.cpus * 1_000_000_000),
            network_disabled=True,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            volumes={str(gate): {"bind": "/gate", "mode": "rw"}},
            detach=True,
        )
        t_start_call = time.monotonic_ns()
        container.start()
        container.reload()
        pid1 = int(container.attrs["State"]["Pid"])
        root_tid = _find_root_tid(pid1)
        cg_path = cgroup_path_of(root_tid)
        row["root_tid"] = root_tid

        tracker_error = ""
        if cfg.use_tracker:
            try:
                pids_current = int((cg_path / "pids.current").read_text())
                tracker.register_cgroup(run_id, cgroup_id_of(cg_path), pids_current)
                tracker.register_root(run_id, root_tid)
            except (TrackerError, OSError, ValueError) as exc:
                tracker_error = f"register: {exc}"

        for ms in cfg.pids_poll_ms:
            pollers[f"poll_pids_{ms}ms"] = _Poller(cg_path / "pids.current", ms)
        for ms in cfg.mem_poll_ms:
            pollers[f"poll_mem_{ms}ms"] = _Poller(cg_path / "memory.current", ms)
        for poller in pollers.values():
            poller.start()

        if cfg.gate_delay_ms:
            time.sleep(cfg.gate_delay_ms / 1000)
        t_release = time.monotonic_ns()
        (gate / "start.ready").touch()

        wait_result = container.wait(timeout=cfg.timeout_s)
        t_exit = time.monotonic_ns()
        row["exit_code"] = wait_result.get("StatusCode")

        for poller in pollers.values():
            poller.stop_event.set()
        for name, poller in pollers.items():
            poller.join(timeout=1)
            row[name] = poller.max_value
            row[f"{name}_samples"] = poller.samples

        # ---- eBPF 측정값 ----
        if cfg.use_tracker and not tracker_error:
            try:
                snap = tracker.snapshot(run_id)
                row.update(
                    user_task_peak=snap.user_task_peak,
                    process_at_peak=snap.process_at_user_task_peak,
                    thread_at_peak=snap.thread_at_user_task_peak,
                    tracker_error_flags=snap.error_flags,
                    exec_start_ns=snap.exec_start_ns,
                    exec_end_ns=snap.exec_end_ns,
                )
                if snap.exec_start_ns and snap.exec_end_ns >= snap.exec_start_ns:
                    row["wall_ebpf_ms"] = (snap.exec_end_ns - snap.exec_start_ns) / 1e6
                    row["gate_to_exec_ms"] = (snap.exec_start_ns - t_release) / 1e6
                    row["end_to_exit_ms"] = (t_exit - snap.exec_end_ns) / 1e6
            except TrackerError as exc:
                tracker_error = f"snapshot: {exc}"
            finally:
                try:
                    tracker.remove(run_id)
                except TrackerError:
                    pass
        row["tracker_error"] = tracker_error

        # ---- 기존 방식 측정값 ----
        row["wall_container_ms"] = (t_exit - t_start_call) / 1e6
        row["wall_gate_ms"] = (t_exit - t_release) / 1e6

        logs = container.logs(stdout=True, stderr=False).decode(errors="replace")
        out = _parse_key_values(logs, "=")
        if "LAB_T0" in out and "LAB_T1" in out:
            row["wall_self_ms"] = (int(out["LAB_T1"]) - int(out["LAB_T0"])) / 1e6
        for key in ("LAB_CREATED", "LAB_FAILED"):
            if key in out:
                row[key.lower()] = int(out[key])

        result_file = gate / "result.txt"
        if result_file.exists():
            for key, value in _parse_key_values(result_file.read_text(), " ").items():
                row[key] = int(value)
        return row
    finally:
        for poller in pollers.values():
            poller.stop_event.set()
        if container is not None:
            try:
                container.remove(force=True)
            except docker.errors.DockerException:
                pass
        shutil.rmtree(gate, ignore_errors=True)
        if own_client:
            client.close()
