#!/usr/bin/env bash
set -euo pipefail

task_mode="${1:---user}"
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "$task_mode" == "--system" ]]; then
  if [[ "$(id -u)" != "0" ]]; then
    echo "Run --system as root; the project environment itself uses a normal user." >&2
    exit 1
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3.12 python3.12-venv python3-pip git curl ca-certificates xz-utils
  exit 0
fi
if [[ "$task_mode" != "--user" ]]; then
  echo "Usage: setup_linux.sh --system | --user" >&2
  exit 2
fi
if [[ "$(id -u)" == "0" ]]; then
  echo "Create the normal Ubuntu user first; do not install this project as root." >&2
  exit 1
fi
cd -- "$task_root"
mkdir -p tmp
python3.12 -c 'import sys; assert sys.version_info[:2] == (3,12)'
python3.12 scripts/install_node_linux.py
export PATH="$HOME/.local/share/wavepacket-node/current/bin:$PATH"
if [[ ! -x .venv/bin/python ]]; then python3.12 -m venv .venv; fi
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install --no-build-isolation -e '.[dev,notebooks]'
npm --prefix frontend ci
.venv/bin/python scripts/build_frontend.py
npm --prefix frontend exec -- playwright install chromium
printf '\nReady. Run .venv/bin/wavepacket serve --port 8766 --open-browser\n'
