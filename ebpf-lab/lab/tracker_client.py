"""eBPF Task tracker 데몬과 통신하는 클라이언트.

CodeGuard runner/metrics/task_tracker.py에서 실험에 필요한 부분만 옮겼다.
원본과 달리 오류 플래그가 있어도 예외를 던지지 않고 값을 그대로 돌려준다.
(측정 실패가 몇 번 일어났는지 세는 것도 실험 대상이기 때문이다.)
"""

import ctypes
import os
import socket
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

CG_TRACKER_MAGIC = 0x43475452
CG_TRACKER_VERSION = 3

CG_OP_HEALTH = 1
CG_OP_REGISTER_CGROUP = 2
CG_OP_REGISTER_ROOT = 3
CG_OP_SNAPSHOT = 4
CG_OP_REMOVE = 5

REQUEST_STRUCT = struct.Struct("<IHH16sQII")
RESPONSE_STRUCT = struct.Struct("<IHHiIIIIIQQ")
DEFAULT_SOCKET = Path("/run/codeguard/task-tracker.sock")


class TrackerError(RuntimeError):
    pass


@dataclass(frozen=True)
class Snapshot:
    root_tid: int
    user_task_peak: int
    process_at_user_task_peak: int
    thread_at_user_task_peak: int
    error_flags: int
    exec_start_ns: int
    exec_end_ns: int


class TrackerClient:
    def __init__(self, socket_path: Path = DEFAULT_SOCKET, timeout: float = 0.5) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def health(self) -> None:
        self._request(CG_OP_HEALTH, UUID(int=0))

    def register_cgroup(self, run_id: UUID, cgroup_id: int, initial_task_count: int) -> None:
        self._request(
            CG_OP_REGISTER_CGROUP,
            run_id,
            cgroup_id=cgroup_id,
            initial_task_count=max(initial_task_count, 1),
        )

    def register_root(self, run_id: UUID, root_tid: int) -> None:
        self._request(CG_OP_REGISTER_ROOT, run_id, root_tid=root_tid)

    def snapshot(self, run_id: UUID) -> Snapshot:
        return self._request(CG_OP_SNAPSHOT, run_id)

    def remove(self, run_id: UUID) -> None:
        self._request(CG_OP_REMOVE, run_id)

    def _request(self, op: int, run_id: UUID, *, cgroup_id: int = 0,
                 root_tid: int = 0, initial_task_count: int = 0) -> Snapshot:
        payload = REQUEST_STRUCT.pack(
            CG_TRACKER_MAGIC, CG_TRACKER_VERSION, op, run_id.bytes,
            cgroup_id, root_tid, initial_task_count,
        )
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET) as conn:
                conn.settimeout(self.timeout)
                conn.connect(str(self.socket_path))
                conn.sendall(payload)
                raw = conn.recv(RESPONSE_STRUCT.size + 1)
        except OSError as exc:
            raise TrackerError(f"tracker communication failed: {exc}") from exc
        if len(raw) != RESPONSE_STRUCT.size:
            raise TrackerError("invalid tracker response length")
        (magic, version, _r, status, root, peak, proc, thr, flags,
         start_ns, end_ns) = RESPONSE_STRUCT.unpack(raw)
        if magic != CG_TRACKER_MAGIC or version != CG_TRACKER_VERSION:
            raise TrackerError("tracker protocol mismatch")
        if status != 0:
            raise TrackerError(f"tracker request failed: op={op} status={status}")
        return Snapshot(root, peak, proc, thr, flags, start_ns, end_ns)


# ---- cgroup 식별 -------------------------------------------------------------

class _FileHandle(ctypes.Structure):
    _fields_ = [
        ("handle_bytes", ctypes.c_uint),
        ("handle_type", ctypes.c_int),
        ("f_handle", ctypes.c_ubyte * 8),
    ]


def cgroup_id_of(path: Path) -> int:
    """cgroup 디렉터리의 커널 cgroup id(= bpf_get_current_cgroup_id 값)를 구한다."""
    libc = ctypes.CDLL(None, use_errno=True)
    fn = libc.name_to_handle_at
    fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(_FileHandle),
                   ctypes.POINTER(ctypes.c_int), ctypes.c_int]
    fn.restype = ctypes.c_int
    handle = _FileHandle(handle_bytes=8)
    mount_id = ctypes.c_int()
    if fn(-100, os.fsencode(path), ctypes.byref(handle), ctypes.byref(mount_id), 0) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err), str(path))
    return int.from_bytes(bytes(handle.f_handle), byteorder=sys.byteorder)


def cgroup_path_of(tid: int, mount: Path = Path("/sys/fs/cgroup")) -> Path:
    for line in Path(f"/proc/{tid}/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            return mount / line.split(":", 2)[2].lstrip("/")
    raise TrackerError(f"cgroup v2 entry not found for tid {tid}")
