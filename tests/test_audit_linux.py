"""A disposable preview must not block Linux lifecycle recovery after writer exit."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from wavepacket.api import RunSupervisor
from wavepacket.config import SimulationConfig
from wavepacket.runner import read_record


@pytest.mark.skipif(sys.platform != "linux", reason="Linux preview pipe termination regression")
@pytest.mark.parametrize("worker_exit", ["completed", "terminated"])
def test_large_preview_cannot_block_refresh_after_worker_exit(tmp_path, worker_exit):
    probe = tmp_path / "preview_lifecycle.py"
    probe.write_text(
        textwrap.dedent(
            """\
            import faulthandler
            import json
            import sys
            import time
            from pathlib import Path
            from wavepacket.api import RunSupervisor
            from wavepacket.config import SimulationConfig
            from wavepacket.storage import acquire_lock

            def main():
                faulthandler.dump_traceback_later(12)
                mode, directory = sys.argv[1:]
                supervisor = RunSupervisor(Path(directory))
                supervisor.open()
                try:
                    config = SimulationConfig.model_validate({
                        "grid": {"bounds": [[-16,16],[-16,16]], "points": [128,128]},
                        "state": {"center": [-2,-2], "momentum": [1,.5], "sigma": [1.5,1.5]},
                        "solver": {"duration": .001 if mode == "completed" else 100, "dt": .001},
                        "sampling": {"snapshots": 2}
                    })
                    record = supervisor.start(config)
                    worker = supervisor.process
                    if mode == "terminated":
                        time.sleep(.4)
                        worker.terminate()
                    worker.join(timeout=10)
                    assert not worker.is_alive(), "The owned test worker did not exit"
                    print(json.dumps({"worker_exitcode": worker.exitcode, "stage": "before_refresh"}), flush=True)
                    supervisor.refresh()
                    expected = "completed" if mode == "completed" else "failed"
                    assert supervisor.active_id is None
                    assert supervisor.get(record["id"])["status"] == expected
                    acquire_lock(Path(directory), ".writer.lock").release()
                    print(json.dumps({"status": expected, "stage": "refreshed"}), flush=True)
                finally:
                    if supervisor.process is not None and supervisor.process.is_alive():
                        supervisor.process.terminate()
                        supervisor.process.join(timeout=3)
                    supervisor.close()
                    faulthandler.cancel_dump_traceback_later()

            if __name__ == "__main__":
                main()
            """
        ),
        encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(probe), worker_exit, str(tmp_path / "runs")],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        output, errors = process.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        # The new session contains only this probe and its owned worker/IPC helpers.
        os.killpg(process.pid, signal.SIGKILL)
        output, errors = process.communicate(timeout=5)
        pytest.fail(f"Preview lifecycle blocked after worker exit:\n{output}\n{errors}")
    assert process.returncode == 0, output + errors
    records = [json.loads(line) for line in output.splitlines()]
    assert records[-1] == {
        "status": "completed" if worker_exit == "completed" else "failed",
        "stage": "refreshed",
    }


def test_live_record_progress_agrees_with_same_run_preview(tmp_path):
    supervisor = RunSupervisor(tmp_path)
    supervisor.open()
    try:
        config = SimulationConfig.model_validate(
            {
                "grid": {"bounds": [[-16, 16], [-16, 16]], "points": [128, 128]},
                "state": {"center": [-2, -2], "momentum": [1, 0.5], "sigma": [1.5, 1.5]},
                "solver": {"duration": 100, "dt": 0.001},
                "sampling": {"snapshots": 2},
            }
        )
        admitted = supervisor.start(config)
        deadline = time.monotonic() + 10
        frame = None
        while time.monotonic() < deadline:
            public = supervisor.get(admitted["id"])
            frame = supervisor.previews.get(admitted["id"])
            if frame is not None and frame["step"] > 0:
                break
            time.sleep(0.02)
        assert frame is not None and 0 < frame["step"] < frame["total_steps"]
        assert frame["run_id"] == admitted["id"]
        assert public["status"] == "running"
        assert public["progress"] == pytest.approx(frame["step"] / frame["total_steps"])
    finally:
        supervisor.close()
    canonical = read_record(supervisor.folder(admitted["id"]))
    public = supervisor.get(admitted["id"])
    assert canonical["status"] == public["status"] == "cancelled"
    assert canonical["progress"] == public["progress"]
