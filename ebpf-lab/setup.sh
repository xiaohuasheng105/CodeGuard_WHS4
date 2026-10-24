#!/usr/bin/env bash
# 실험 환경 준비: 측정기 확인, 실험 이미지 빌드, Python 가상환경 생성
# 사용법: ebpf-lab 폴더에서  bash setup.sh
set -Eeuo pipefail
cd "$(dirname "$0")"

SOCK=/run/codeguard/task-tracker.sock

echo "== 1. eBPF 측정기 확인"
if [[ -S "$SOCK" ]] && systemctl is-active --quiet codeguard-task-tracker; then
  echo "   이미 설치된 codeguard-task-tracker 서비스를 사용합니다."
else
  echo "   측정기 서비스가 없습니다. native/ 의 소스로 빌드·설치합니다."
  sudo apt-get install -y clang llvm libbpf-dev build-essential pkg-config \
    linux-tools-common "linux-tools-$(uname -r)"
  make -C native
  sudo groupadd -f codeguard
  sudo install -m 0755 native/codeguard-task-tracker /usr/local/libexec/codeguard-task-tracker
  sudo install -m 0644 native/codeguard-task-tracker.service /etc/systemd/system/
  sudo usermod -aG codeguard "$(id -un)"
  sudo systemctl daemon-reload
  sudo systemctl enable --now codeguard-task-tracker
  echo "   설치했습니다. codeguard 그룹 반영을 위해 로그아웃 후 다시 로그인하세요."
fi

echo "== 2. 실험 이미지 빌드 (codeguard-lab:dev)"
docker build -f container/Dockerfile -t codeguard-lab:dev .

echo "== 3. Python 가상환경"
[[ -d .venv ]] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt

echo "== 4. 동작 확인 (smoke)"
.venv/bin/python lab/experiments.py smoke
