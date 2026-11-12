"""Profile a validated 2D case, HDF5 I/O, PNG rendering and HTML reporting.

Run with the project's Python interpreter. Each timed component has one warm-up
and three retained repetitions. These small warm-cache timings are measurements,
not a throughput guarantee or a comparison against an unimplemented C++ engine.
"""
from __future__ import annotations

import argparse
import cProfile
import csv
import hashlib
import io
import json
import os
import platform
import pstats
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import psutil
import scipy

from wavepacket.benchmarks import _coherent_reference
from wavepacket.config import SimulationConfig
from wavepacket.model import initial_state, make_grid
from wavepacket.observables import measure
from wavepacket.operators import potential
from wavepacket.propagators import Stepper, make_stepper
from wavepacket.validation import fixture, state_error


def _configuration() -> SimulationConfig:
    config = fixture(ndim=2, points=128, length=20.0, duration=1.0, dt=0.001,
                     state={"kind": "ho_coherent", "center": [2.0, -1.0], "momentum": [0.5, 1.0], "sigma": [1.0, 1.0],
                            "params": {"omega": [1.0, 1.5], "angle": np.pi / 6}},
                     potential_spec={"kind": "harmonic", "params": {"omega": [1.0, 1.5], "angle": np.pi / 6}})
    data = config.model_dump()
    data["name"] = "profile-validated-rotated-oscillator"
    data["sampling"].update(snapshots=9, observable_every=125, screen_x=None)
    return SimulationConfig.model_validate(data)


def _prepare(config: SimulationConfig):
    grid = make_grid(config.grid)
    values = potential(config, grid)
    psi = initial_state(config, grid)
    return grid, values, psi, make_stepper(config, grid, values)


def _advance(step: Stepper, psi: np.ndarray, count: int, dt: float) -> np.ndarray:
    for _ in range(count):
        psi = step(psi, dt)
    return psi


def _timings(samples: list[float]) -> dict:
    return {"seconds": samples, "median_seconds": statistics.median(samples),
            "minimum_seconds": min(samples), "maximum_seconds": max(samples)}


def _repeat(function, repeats: int = 3) -> dict:
    function()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        samples.append(time.perf_counter() - started)
    return _timings(samples)


def _write_h5(path: Path, states: np.ndarray, times: np.ndarray, grid, values: np.ndarray) -> None:
    # Same complex dtype, frame chunks and gzip level as production artifacts.
    with h5py.File(path, "w") as store:
        store.create_dataset("x", data=grid.axes[0])
        store.create_dataset("y", data=grid.axes[1])
        store.create_dataset("potential", data=values)
        store.create_dataset("absorber", data=np.zeros(grid.shape))
        dataset = store.create_dataset("psi", shape=(0, *grid.shape), maxshape=(None, *grid.shape),
                                       chunks=(1, *grid.shape), compression="gzip", compression_opts=1, dtype="complex128")
        for index, state in enumerate(states):
            dataset.resize(index + 1, axis=0)
            dataset[index] = state
        store.create_dataset("time", data=times)


def _render_png(path: Path, state: np.ndarray, grid) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(figsize=(7, 4), layout="constrained")
    dx, dy = grid.spacing
    extent = (grid.axes[0][0] - dx / 2, grid.axes[0][-1] + dx / 2,
              grid.axes[1][0] - dy / 2, grid.axes[1][-1] + dy / 2)
    image = axes.imshow(np.abs(state)**2, origin="lower", extent=extent, cmap="magma", aspect="equal")
    axes.set(xlabel="x [dimensionless]", ylabel="y [dimensionless]", title="Validated rotated-oscillator density")
    figure.colorbar(image, ax=axes, label="Probability density")
    figure.savefig(path, dpi=120)
    plt.close(figure)


def profile(output: str | Path) -> dict[str, Any]:
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".matplotlib"))
    config = _configuration()
    preparation, stepping, diagnostics = [], [], []
    final = None
    for repetition in range(4):
        started = time.perf_counter()
        grid, values, psi, step = _prepare(config)
        setup_time = time.perf_counter() - started
        started = time.perf_counter()
        final = _advance(step, psi, config.n_steps, config.solver.dt)
        step_time = time.perf_counter() - started
        started = time.perf_counter()
        last_metrics = measure(final, grid, values)
        diagnostic_time = time.perf_counter() - started
        if repetition:
            preparation.append(setup_time)
            stepping.append(step_time)
            diagnostics.append(diagnostic_time)
    assert final is not None
    reference = _coherent_reference(grid, config.solver.duration)
    error = state_error(final, reference, grid, align=True)
    norm_drift = abs(float(np.vdot(final, final).real * grid.cell_volume) - 1)
    if error >= 1e-5 or norm_drift >= 1e-11:
        raise RuntimeError(f"profiling fixture failed its numerical guard: state={error}, norm={norm_drift}")

    grid, values, psi, step = _prepare(config)
    profiler = cProfile.Profile()
    profiled = profiler.runcall(_advance, step, psi, config.n_steps, config.solver.dt)
    if state_error(profiled, final, grid) > 1e-12:
        raise RuntimeError("profiling changed the computed state")
    profiler.dump_stats(str(output / "core.pstats"))
    text = io.StringIO()
    stats = pstats.Stats(profiler, stream=text).sort_stats("cumulative")
    stats.print_stats(30)
    (output / "profile.txt").write_text(text.getvalue(), encoding="utf-8")
    functions = []
    # These runtime pstats fields are absent from some stdlib type stubs.
    profile_data: Any = stats
    raw_stats = profile_data.stats
    profiled_total = float(profile_data.total_tt)
    for (filename, line, function), (primitive, calls, self_time, cumulative, _) in sorted(raw_stats.items(), key=lambda item: item[1][3], reverse=True):
        functions.append({"file": filename, "line": line, "function": function, "primitive_calls": primitive,
                          "total_calls": calls, "self_seconds": self_time, "cumulative_seconds": cumulative})
    fft_entries = [row for row in functions if row["file"] == "~" and "fft." in row["function"]
                   and any(name in row["function"] for name in ("c2c", "r2c", "c2r"))]
    compiled_fft = sum(row["self_seconds"] for row in fft_entries)
    propagator_self = sum(row["self_seconds"] for row in functions if row["file"].replace("\\", "/").endswith("/propagators.py"))

    # A separate pass collects nine genuine complex snapshots; its time is not
    # included in the pure-step or I/O measurements.
    grid, values, psi, step = _prepare(config)
    snapshots, times = [psi.copy()], [0.0]
    for index in range(config.n_steps):
        psi = step(psi)
        if (index + 1) % 125 == 0 or index + 1 == config.n_steps:
            snapshots.append(psi.copy())
            times.append((index + 1) * config.solver.dt)
    states = np.stack(snapshots)
    time_values = np.asarray(times)
    h5_path = output / "io-fixture.h5"
    write_timing = _repeat(lambda: _write_h5(h5_path, states, time_values, grid, values))

    def read_states() -> np.ndarray:
        with h5py.File(h5_path, "r") as store:
            return store["psi"][:]

    read_timing = _repeat(read_states)
    roundtrip = bool(np.array_equal(read_states(), states))
    if not roundtrip:
        raise RuntimeError("HDF5 complex snapshots did not round-trip exactly")
    render_timing = _repeat(lambda: _render_png(output / "rendered-density.png", states[-1], grid))

    # Prepare the actual production reporter's input format. This is explicitly
    # a profiling fixture, not an end-to-end runner-throughput measurement.
    report_folder = output / "report-fixture"
    report_folder.mkdir(exist_ok=True)
    (report_folder / "state.h5").write_bytes(h5_path.read_bytes())
    (report_folder / "config.json").write_text(config.model_dump_json(indent=2), encoding="utf-8")
    summary = {"status": "completed", "final": last_metrics,
               "warnings": ["Profiling fixture: timings are warm-cache measurements on one128x128 problem, not a general performance guarantee."]}
    (report_folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    rows = [{"time": float(t), **measure(state, grid, values)} for state, t in zip(states, time_values, strict=True)]
    with (report_folder / "observables.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    from wavepacket.reporting import report_run

    report_timing = _repeat(lambda: report_run(report_folder))
    source_files = [Path(__file__), *[Path(__file__).parents[1] / "src" / "wavepacket" / name
                                    for name in ("config.py", "model.py", "operators.py", "propagators.py", "observables.py", "reporting.py")]]
    source_hashes = {str(path.relative_to(Path(__file__).parents[1])): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    (report_folder / "manifest.json").write_text(json.dumps({"configuration": config.model_dump(mode="json"),
                "source_sha256": source_hashes, "note": "Explicit profiling fixture; not a runner-produced throughput trial."}, indent=2), encoding="utf-8")
    report: dict[str, Any] = {
        "schema_version": 1, "created_utc": datetime.now(UTC).isoformat(), "status": "measured",
        "configuration": config.model_dump(mode="json"), "warmups": 1, "repeats": 3,
        "numerical_guard": {"phase_aligned_state_error": error, "norm_drift": norm_drift,
                            "limits": {"state_error": 1e-5, "norm_drift": 1e-11}, "passed": True},
        "timings": {"setup": _timings(preparation), "pure_stepping": _timings(stepping),
                    "final_diagnostics": _timings(diagnostics), "gzip1_hdf5_write": write_timing,
                    "hdf5_read": read_timing, "single_png_render": render_timing,
                    "production_html_report_including_two_plot_renders": report_timing},
        "io": {"frames": len(states), "shape": list(states.shape), "raw_complex_bytes": states.nbytes,
               "hdf5_bytes": h5_path.stat().st_size, "bitwise_roundtrip": roundtrip,
               "compression": "gzip level 1, one complex128 frame per chunk"},
        "profile": {"total_seconds": profiled_total, "compiled_fft_self_seconds": compiled_fft,
                    "compiled_fft_functions": [row["function"] for row in fft_entries],
                    "compiled_fft_self_fraction": compiled_fft / profiled_total if profiled_total else 0,
                    "propagator_self_seconds": propagator_self, "top_cumulative_functions": functions[:30]},
        "environment": {"python": platform.python_version(), "numpy": np.__version__, "scipy": scipy.__version__,
                        "h5py": h5py.__version__, "platform": platform.platform(), "processor": platform.processor(),
                        "logical_cpus": psutil.cpu_count(), "memory_bytes": psutil.virtual_memory().total},
        "source_sha256": source_hashes,
        "interpretation": [
            "Profiled pure stepping excludes setup, diagnostics, frame collection, serialization and rendering.",
            "Compiled FFT kernel self time is summed without double-counting nested cumulative times; backend names are recorded from the actual profile.",
            "Propagator self time includes NumPy array operations whose compiled work cProfile may not expose separately; it is not a pure-Python fraction.",
            "PNG rendering and production HTML reporting are independent trials. The latter includes two renders and artifact reads; their timings overlap and must not be added as separate phases.",
            "HDF5 reads are warm-cache reads; writes include compression, opening and closing but no explicit fsync. These are not cold-disk benchmarks.",
            "No native prototype was benchmarked. Compiled FFT delegation and measured I/O/rendering costs motivate retaining the current implementation; they do not prove custom C++ could never help."]}
    (output / "profile.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(__file__).parents[1] / "results" / "profiling")
    arguments = parser.parse_args()
    report = profile(arguments.output)
    print(json.dumps({"status": report["status"], "guard": report["numerical_guard"],
                      "median_seconds": {name: data["median_seconds"] for name, data in report["timings"].items()},
                      "compiled_fft_profile_fraction": report["profile"]["compiled_fft_self_fraction"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
