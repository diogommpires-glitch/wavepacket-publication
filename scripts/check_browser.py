"""Run real browser workflows against an isolated, explicitly owned API process."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import suppress
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    node = shutil.which("node")
    if node is None:
        raise SystemExit("Node 24 is required for browser workflows")
    (ROOT / "tmp").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="browser-", dir=ROOT / "tmp") as directory:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        command = [
            sys.executable,
            "-m",
            "wavepacket",
            "serve",
            "--port",
            str(port),
            "--data-dir",
            directory,
        ]
        with (Path(directory) / "server.log").open("w", encoding="utf-8") as log:
            server = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            server_owner = psutil.Process(server.pid)
            try:
                deadline = time.monotonic() + 30
                while True:
                    if server.poll() is not None:
                        raise RuntimeError(f"API exited with {server.returncode}; see {log.name}")
                    try:
                        with urllib.request.urlopen(f"{base}/api/health", timeout=1) as response:
                            health = json.load(response)
                        if health["status"] == "ok":
                            break
                    except (urllib.error.URLError, TimeoutError):
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"API did not become ready at {base}") from None
                        time.sleep(0.1)
                environment = dict(os.environ, WAVEPACKET_URL=base)
                result = subprocess.run(
                    [node, "frontend/tests/browser.mjs"], cwd=ROOT, env=environment, check=False
                )
                return result.returncode
            finally:
                # Windows terminate bypasses ASGI shutdown. Join this server's
                # children before removing their temporary scientific files.
                try:
                    children = server_owner.children(recursive=True)
                except psutil.NoSuchProcess:
                    children = []
                for child in children:
                    with suppress(psutil.NoSuchProcess):
                        child.terminate()
                _, alive = psutil.wait_procs(children, timeout=5)
                for child in alive:
                    with suppress(psutil.NoSuchProcess):
                        child.kill()
                psutil.wait_procs(alive, timeout=5)
                server.terminate()
                try:
                    server.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait(timeout=10)
                destination = ROOT / "frontend/tests/artifacts"
                destination.mkdir(parents=True, exist_ok=True)
                log.flush()
                shutil.copyfile(log.name, destination / "server.log")


if __name__ == "__main__":
    raise SystemExit(main())
