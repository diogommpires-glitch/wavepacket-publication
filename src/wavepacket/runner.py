"""Execute simulations once and persist scientifically inspectable artifacts."""

from __future__ import annotations

import csv
import errno
import hashlib
import importlib.metadata
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np

from .config import SimulationConfig, config_fingerprint
from .contracts import RunRecord
from .storage import acquire_lock, process_identity

ARTIFACTS = {
    "config.json",
    "manifest.json",
    "observables.csv",
    "state.h5",
    "report.html",
    "summary.json",
    "density.png",
    "diagnostics.png",
    "record.json",
    "screen.png",
    "screen.csv",
}
CONTROL_HEADROOM = 32 * 1024**2
MAX_PREVIEW_BYTES = 8 * 1024**2
OBSERVABLE_COLUMNS = 128


class OutputBudgetExceeded(RuntimeError):
    """The next artifact allocation would exceed the declared output budget."""


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.ndarray):
        return json_safe(value.tolist())
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (float, np.floating)):
        if not math.isfinite(value):
            raise ValueError("non-finite numerical output cannot be serialized as a measurement")
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def _retry_windows_sharing[T](operation: Callable[[], T]) -> T:
    """Bound temporary Windows read/delete sharing conflicts without hiding storage failure."""
    deadline = time.monotonic() + 2
    while True:
        try:
            return operation()
        except PermissionError as error:
            native_code = getattr(error, "winerror", None)
            # CRT text reads discard WinError and expose only EACCES.
            sharing_conflict = native_code in (5, 32, 33) or (
                native_code is None and error.errno == errno.EACCES
            )
            if sys.platform != "win32" or not sharing_conflict or time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(json_safe(value), indent=2, allow_nan=False), encoding="utf-8")
    _retry_windows_sharing(lambda: temp.replace(path))


def resolve_config(config: SimulationConfig | dict | str | Path) -> SimulationConfig:
    if isinstance(config, SimulationConfig):
        return config
    if isinstance(config, (str, Path)):
        return SimulationConfig.model_validate_json(Path(config).read_text(encoding="utf-8"))
    return SimulationConfig.model_validate(config)


def estimate_resources(config: SimulationConfig) -> dict:
    points = math.prod(config.grid.points)
    frames = min(config.sampling.snapshots, config.n_steps + 1)
    observations = 1 + config.n_steps // config.sampling.observable_every
    observations += int(config.n_steps % config.sampling.observable_every != 0)
    state_bytes = points * frames * 16
    screen_bytes = (
        frames * config.grid.points[-1] * 16 if config.sampling.screen_x is not None else 0
    )
    csv_bytes = (observations + 1) * (OBSERVABLE_COLUMNS * 32 + 2)
    diagnostics_bytes = frames * 8192
    static_bytes = points * 16 + sum(config.grid.points) * 8
    total = (
        CONTROL_HEADROOM + state_bytes + screen_bytes + csv_bytes + diagnostics_bytes + static_bytes
    )
    preview_bytes = min(points, 256**2) * 32 * 6 * 3
    working = 128 * 1024**2 + points * 16 * 24 + preview_bytes + 2000 * OBSERVABLE_COLUMNS * 24
    max_working = config.budget.max_working_bytes
    errors = []
    if total > config.budget.max_output_bytes:
        errors.append(
            f"estimated total artifact allocation {total} bytes exceeds max_output_bytes={config.budget.max_output_bytes}"
        )
    if working > max_working:
        errors.append(
            f"estimated working memory {working} bytes exceeds max_working_bytes={max_working}"
        )
    return {
        "dimension": len(config.grid.points),
        "points": points,
        "steps": config.n_steps,
        "snapshots": frames,
        "observations": observations,
        "uncompressed_state_bytes": state_bytes,
        "estimated_diagnostics_bytes": csv_bytes + diagnostics_bytes,
        "estimated_screen_bytes": screen_bytes,
        "control_report_reserve_bytes": CONTROL_HEADROOM,
        "disposable_preview_reserve_bytes": 2 * MAX_PREVIEW_BYTES,
        "estimated_total_output_bytes": total,
        "estimated_working_bytes": working,
        "within_budget": not errors,
        "errors": errors,
        "max_allocation_overshoot_bytes": points * 16 + 8192,
        "note": "Conservative allocation estimates include sampled diagnostics and 32 MiB control/report headroom, including two bounded 8 MiB disposable preview JSON files. Output is a soft allocation ceiling, not a filesystem hard quota; one bounded HDF5 allocation may overshoot. Memory excludes unrelated processes.",
    }


def enforce_resources(config: SimulationConfig) -> dict:
    estimate = estimate_resources(config)
    if estimate["errors"]:
        raise ValueError("; ".join(estimate["errors"]))
    return estimate


def provenance(config: SimulationConfig) -> dict:
    root = Path.cwd().resolve()
    revision, dirty = None, None
    try:
        revision = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, stderr=subprocess.DEVNULL, timeout=3
            )
            .decode()
            .strip()
        )
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=root, stderr=subprocess.DEVNULL, timeout=3
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        revision, dirty = None, None
    versions = {}
    for package in ("wavepacket-lab", "numpy", "scipy", "h5py", "pydantic", "filelock"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "uninstalled"
    lock = root / "requirements-lock.txt"
    return {
        "created_at": timestamp(),
        "config_sha256": config_fingerprint(config),
        "code_revision": revision,
        "code_dirty": dirty,
        "source_sha256": {
            source.name: hashlib.sha256(source.read_bytes()).hexdigest()
            for source in sorted(Path(__file__).parent.glob("*.py"))
        },
        "dependency_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest()
        if lock.exists()
        else None,
        "python": sys.version,
        "platform": platform.platform(),
        "cpu": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "versions": versions,
        "threads": {
            k: os.environ.get(k)
            for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")
        },
        "array_order": "physical axes x,y; array shape ny,nx; C order; x fastest",
        "scientific_dtype": "complex128",
        "numerical_units": "hbar=m=1",
        "boundary_model": "periodic Fourier grid; CAP approximates an open boundary where enabled",
    }


def _edge_mass(psi: np.ndarray, cell_volume: float) -> float:
    mask = np.zeros(psi.shape, dtype=bool)
    for axis, n in enumerate(psi.shape):
        lower, upper = [slice(None)] * psi.ndim, [slice(None)] * psi.ndim
        width = max(2, n // 64)
        lower[axis], upper[axis] = slice(0, width), slice(-width, None)
        mask[tuple(lower)], mask[tuple(upper)] = True, True
    return float(np.sum(np.abs(psi[mask]) ** 2) * cell_volume)


def frame_payload(
    psi,
    grid,
    V,
    time_value: float,
    metrics: dict,
    step: int,
    total_steps: int,
    max_axis: int = 128,
    kinetic: str = "spectral",
    screen: dict | None = None,
    *,
    validity: dict | None = None,
    run_id: str | None = None,
    config_sha256: str | None = None,
    density_scale_max: float | None = None,
    density_scale_scope: str = "running_max",
) -> dict:
    from .observables import current, measurement_validity

    slices = tuple(slice(None, None, max(1, math.ceil(n / max_axis))) for n in psi.shape)
    reduced = psi[slices]
    strides = list(reversed([s.step for s in slices]))
    axes = {
        key: a[::stride].tolist()
        for key, a, stride in zip(("x", "y"), grid.axes, strides, strict=False)
    }
    peak = float(np.max(np.abs(psi) ** 2))
    result = {
        "time": time_value,
        "dimension": psi.ndim,
        "shape": list(reduced.shape),
        "axes": axes,
        "density": (np.abs(reduced) ** 2).tolist(),
        "phase": np.angle(reduced).tolist(),
        "potential": V[slices].tolist(),
        "observables": metrics,
        "validity": validity or measurement_validity(psi, grid),
        "step": step,
        "total_steps": total_steps,
        "run_id": run_id,
        "config_sha256": config_sha256,
        "density_scale_max": peak if density_scale_max is None else density_scale_max,
        "density_scale_scope": density_scale_scope,
    }
    for name, component in zip(("x", "y"), current(psi, grid, kinetic), strict=False):
        result[f"current_{name}"] = component[slices].tolist()
    result["current_location"] = (
        "positive half-grid faces" if kinetic == "fd2" else "grid nodes; continuum-form diagnostic"
    )
    if screen is not None:
        result["screen"] = screen
    return json_safe(result)


def _screen_current(psi, grid, kinetic: str, index: int) -> np.ndarray:
    if kinetic == "fd2":
        return (
            np.imag(np.conj(psi[:, index]) * psi[:, (index + 1) % psi.shape[-1]]) / grid.spacing[0]
        )
    from scipy import fft

    k = 2 * np.pi * fft.fftfreq(grid.points[0], d=grid.spacing[0])
    derivative = fft.ifft(1j * k[None, :] * fft.fft(psi, axis=-1), axis=-1)
    return np.imag(np.conj(psi[:, index]) * derivative[:, index])


def run_simulation(
    config,
    output_root: str | Path = "runs",
    *,
    run_id: str | None = None,
    progress: Callable[[dict], str | None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    admitted: Callable[[dict], None] | None = None,
) -> dict:
    config = resolve_config(config)
    resources = enforce_resources(config)
    root = Path(output_root).expanduser().resolve()
    lease = acquire_lock(root, ".writer.lock")
    try:
        return _execute_run(
            config, root, resources, run_id or uuid.uuid4().hex, progress, cancelled, admitted
        )
    finally:
        lease.release()


def _execute_run(config, root, resources, run_id, progress, cancelled, admitted):
    from .model import initial_state, make_grid
    from .observables import measure, measurement_validity
    from .operators import absorber, potential
    from .propagators import make_stepper

    if not run_id.isalnum() or len(run_id) > 64:
        raise ValueError("run_id must be an alphanumeric identifier")
    folder = root / run_id
    folder.mkdir(parents=True, exist_ok=False)
    record = {
        "schema_version": 2,
        "id": run_id,
        "status": "running",
        "progress": 0.0,
        "created_at": timestamp(),
        "config": config.model_dump(mode="json"),
        "warnings": [],
        "path": str(folder),
        "resources": resources,
        "owner": process_identity(),
        "scientific_status": "running",
        "report_status": "pending",
    }
    manifest: dict = {}
    summary: dict = {}
    started = time.perf_counter()
    try:
        write_json(folder / "record.json", record)
        write_json(folder / "config.json", record["config"])
        manifest = provenance(config)
        write_json(folder / "manifest.json", manifest)
        if admitted:
            admitted(record)
        grid = make_grid(config.grid)
        V, W = potential(config, grid), absorber(config, grid)
        psi = initial_state(config, grid)
        stepper = make_stepper(config, grid, V, W)
        initial_norm = float(np.sum(np.abs(psi) ** 2) * grid.cell_volume)
        sample_steps = set(
            np.rint(
                np.linspace(0, config.n_steps, min(config.sampling.snapshots, config.n_steps + 1))
            )
            .astype(int)
            .tolist()
        )
        t, absorption_integral, last_preview = 0.0, 0.0, 0.0
        preview_warning = None
        rate = float(2 * np.sum(W * np.abs(psi) ** 2) * grid.cell_volume)
        max_norm_drift, max_edge, max_saved_density, row_count = 0.0, 0.0, 0.0, 0
        metrics: dict = {}
        validity: dict = {}
        screen_index, screen_x = None, None
        screen_integral = screen_previous = None
        if config.sampling.screen_x is not None:
            face_shift = grid.spacing[0] / 2 if config.solver.kinetic == "fd2" else 0.0
            coordinates = grid.axes[0] + face_shift
            screen_index = int(np.argmin(abs(coordinates - config.sampling.screen_x)))
            screen_x = float(coordinates[screen_index])
            screen_integral = np.zeros(grid.points[1])
            screen_previous = _screen_current(psi, grid, config.solver.kinetic, screen_index)
        payload_bytes = V.nbytes + W.nbytes + sum(a.nbytes for a in grid.axes)

        def reserve(count: int, label: str):
            nonlocal payload_bytes
            if payload_bytes + count + CONTROL_HEADROOM > config.budget.max_output_bytes:
                raise OutputBudgetExceeded(
                    f"{label} would exceed max_output_bytes={config.budget.max_output_bytes}"
                )
            payload_bytes += count

        def sample(step):
            nonlocal max_norm_drift, max_edge, metrics, validity
            if not np.isfinite(psi).all():
                raise FloatingPointError(
                    "State contains non-finite values; no numerical correction was applied"
                )
            metrics = measure(
                psi, grid, V, kinetic=config.solver.kinetic, W=W, initial_norm=initial_norm
            )
            validity = measurement_validity(psi, grid, initial_norm)
            surviving = float(np.sum(np.abs(psi) ** 2) * grid.cell_volume)
            edge = _edge_mass(psi, grid.cell_volume)
            metrics.update(
                time=t,
                step=step,
                norm=surviving,
                absorbed_probability=stepper.total_absorbed,
                probability_budget_residual=surviving + stepper.total_absorbed - initial_norm,
                absorption_rate_integral=absorption_integral,
                edge_probability=edge,
                conditional_valid=float(validity["conditional_status"] == "resolved"),
            )
            max_norm_drift = max(max_norm_drift, abs(surviving - initial_norm))
            max_edge = max(max_edge, edge)

        def screen_payload():
            if screen_index is None:
                return None
            assert screen_integral is not None
            return {
                "x": screen_x,
                "requested_x": config.sampling.screen_x,
                "density_x": float(grid.axes[0][screen_index]),
                "y": grid.axes[1].tolist(),
                "current_integral": screen_integral.tolist(),
                "density": (np.abs(psi[:, screen_index]) ** 2).tolist(),
                "time": t,
                "definition": "time-integrated signed probability current; not detector counts",
                "quadrature": "trapezoidal current at every numerical timestep",
                "current_location": "positive x half-grid face"
                if config.solver.kinetic == "fd2"
                else "x grid node",
            }

        def notify(step):
            nonlocal preview_warning
            if progress:
                warning = progress(
                    {
                        "status": "running",
                        "progress": step / config.n_steps,
                        "frame": frame_payload(
                            psi,
                            grid,
                            V,
                            t,
                            metrics,
                            step,
                            config.n_steps,
                            kinetic=config.solver.kinetic,
                            screen=screen_payload(),
                            validity=validity,
                            run_id=run_id,
                            config_sha256=manifest["config_sha256"],
                            density_scale_max=max(
                                max_saved_density, float(np.max(np.abs(psi) ** 2))
                            ),
                        ),
                    }
                )
                if warning is not None and preview_warning is None:
                    preview_warning = warning

        status, last_step = "completed", 0
        with (
            h5py.File(folder / "state.h5.partial", "w") as store,
            (folder / "observables.csv").open("w", newline="", encoding="utf-8") as stream,
        ):
            store.attrs.update(
                format_version=2, config_json=config.model_dump_json(), initial_norm=initial_norm
            )
            for name, axis in zip(("x", "y"), grid.axes, strict=False):
                store.create_dataset(name, data=axis)
            store.create_dataset("potential", data=V)
            store.create_dataset("absorber", data=W)
            states = store.create_dataset(
                "psi",
                shape=(0, *psi.shape),
                maxshape=(None, *psi.shape),
                chunks=(1, *psi.shape),
                compression="gzip",
                compression_opts=1,
                dtype="complex128",
            )
            times = store.create_dataset("time", shape=(0,), maxshape=(None,), dtype="float64")
            diagnostics = store.create_dataset(
                "diagnostics_json", shape=(0,), maxshape=(None,), dtype=h5py.string_dtype("utf-8")
            )
            screen_states = screen_densities = None
            if screen_index is not None:
                store.attrs.update(
                    screen_x=screen_x, screen_density_x=float(grid.axes[0][screen_index])
                )
                screen_states = store.create_dataset(
                    "screen_integral",
                    shape=(0, grid.points[1]),
                    maxshape=(None, grid.points[1]),
                    dtype="float64",
                )
                screen_densities = store.create_dataset(
                    "screen_density",
                    shape=(0, grid.points[1]),
                    maxshape=(None, grid.points[1]),
                    dtype="float64",
                )
            fieldnames = None
            last_row_time = None

            def write_observable():
                nonlocal row_count, fieldnames, last_row_time
                buffer = io.StringIO(newline="")
                writer = csv.writer(buffer)
                if fieldnames is None:
                    fieldnames = list(metrics)
                    writer.writerow(fieldnames)
                writer.writerow([metrics[key] for key in fieldnames])
                text = buffer.getvalue()
                reserve(len(text.encode("utf-8")), "diagnostic row")
                stream.write(text)
                row_count += 1
                last_row_time = t

            def save_checkpoint():
                nonlocal max_saved_density
                encoded = json.dumps(
                    json_safe({"observables": metrics, "validity": validity}), allow_nan=False
                )
                extra = psi.nbytes + len(encoded.encode("utf-8")) + 4096
                if screen_index is not None:
                    extra += grid.points[1] * 16
                reserve(extra, "scientific checkpoint")
                index = len(times)
                for dataset in (states, times, diagnostics):
                    dataset.resize(index + 1, axis=0)
                states[index], times[index], diagnostics[index] = psi, t, encoded
                max_saved_density = max(max_saved_density, float(np.max(np.abs(psi) ** 2)))
                if screen_states is not None:
                    assert screen_densities is not None
                    screen_states.resize(index + 1, axis=0)
                    screen_densities.resize(index + 1, axis=0)
                    screen_states[index], screen_densities[index] = (
                        screen_integral,
                        np.abs(psi[:, screen_index]) ** 2,
                    )

            for step in range(config.n_steps + 1):
                if step:
                    if cancelled and cancelled():
                        status = "cancelled"
                        break
                    dt = min(config.solver.dt, config.solver.duration - t)
                    psi = stepper(psi, dt=dt)
                    t = (
                        config.solver.duration
                        if step == config.n_steps
                        else step * config.solver.dt
                    )
                    if screen_index is not None:
                        next_current = _screen_current(
                            psi, grid, config.solver.kinetic, screen_index
                        )
                        screen_integral += 0.5 * dt * (screen_previous + next_current)
                        screen_previous = next_current
                    if config.boundary.kind == "cap":
                        next_rate = float(2 * np.sum(W * np.abs(psi) ** 2) * grid.cell_volume)
                        absorption_integral += 0.5 * dt * (rate + next_rate)
                        rate = next_rate
                last_step = step
                observation = step % config.sampling.observable_every == 0 or step == config.n_steps
                checkpoint = step in sample_steps
                now = time.perf_counter()
                preview = bool(
                    progress and (step == 0 or step == config.n_steps or now - last_preview >= 0.2)
                )
                if observation or checkpoint or preview:
                    sample(step)
                if observation:
                    write_observable()
                if checkpoint:
                    save_checkpoint()
                if preview:
                    notify(step)
                    last_preview = now
            if status == "cancelled":
                sample(last_step)
                if last_row_time != t:
                    write_observable()
                if not len(times) or float(times[-1]) != t:
                    save_checkpoint()
                notify(last_step)
            store.attrs.update(status=status, completed_time=t, density_scale_max=max_saved_density)
            saved_snapshots = len(times)
        (folder / "state.h5.partial").replace(folder / "state.h5")
        warnings = [
            "Fixed preset evidence does not certify arbitrary edited settings; norm conservation alone does not establish accuracy."
        ]
        if preview_warning is not None:
            warnings.append(preview_warning)
        if max_edge > 1e-4:
            warnings.append(
                "Probability reached the outer grid region; inspect domain/CAP evidence."
            )
        if config.boundary.kind == "cap":
            warnings.append(
                "CAP intentionally removes norm. Conditional measurements are withheld below the reporting floor."
            )
        if metrics.get("high_k_fraction") is not None and metrics["high_k_fraction"] > 1e-4:
            warnings.append(
                "Significant high-frequency content may invalidate a line-domain uncertainty interpretation."
            )
        record.update(
            status="finalizing",
            progress=t / config.solver.duration,
            scientific_status=status,
            warnings=warnings,
        )
        write_json(folder / "record.json", record)
        if progress:
            progress({"status": "finalizing", "progress": t / config.solver.duration})
        summary.update(
            status=status,
            scientific_status=status,
            report_status="pending",
            final=metrics,
            validity=validity,
            elapsed_seconds=time.perf_counter() - started,
            snapshots=saved_snapshots,
            observations=row_count,
            max_norm_drift=max_norm_drift,
            max_saved_density=max_saved_density,
            warnings=warnings,
            accuracy="unverified configuration; consult exact independent validation conditions",
        )
        write_json(folder / "summary.json", summary)
        from .reporting import report_run

        report_run(folder)
        record["report_status"] = summary["report_status"] = "completed"
        write_json(folder / "summary.json", summary)
        actual_bytes = sum(path.stat().st_size for path in folder.iterdir() if path.is_file())
        if (
            actual_bytes
            > config.budget.max_output_bytes + resources["max_allocation_overshoot_bytes"]
        ):
            raise OutputBudgetExceeded(
                f"artifact total {actual_bytes} bytes exceeds the bounded output allocation"
            )
        manifest["artifact_sha256"] = {}
        for artifact in folder.iterdir():
            if artifact.is_file() and artifact.name not in ("manifest.json", "record.json"):
                with artifact.open("rb") as source:
                    manifest["artifact_sha256"][artifact.name] = hashlib.file_digest(
                        source, "sha256"
                    ).hexdigest()
        manifest.update(status=status, finished_at=timestamp(), artifact_bytes=actual_bytes)
        write_json(folder / "manifest.json", manifest)
        record.update(status=status, summary=summary, finished_at=timestamp())
        write_json(folder / "record.json", record)
        return record
    except BaseException as exc:
        record.update(
            status="failed", error=f"{type(exc).__name__}: {exc}", finished_at=timestamp()
        )
        if record["scientific_status"] == "running":
            record["scientific_status"] = "failed"
        if record["report_status"] != "completed":
            record["report_status"] = "failed"
        summary.update(
            status="failed",
            scientific_status=record["scientific_status"],
            report_status=record["report_status"],
            error=record["error"],
        )
        manifest.update(status="incomplete", error=record["error"])
        for name, value in (
            ("summary.json", summary),
            ("manifest.json", manifest),
            ("record.json", record),
        ):
            try:
                write_json(folder / name, value)
            except OSError as persistence_error:
                record["persistence_error"] = str(persistence_error)
        raise


def read_record(folder: Path) -> dict:
    content = _retry_windows_sharing(lambda: (folder / "record.json").read_text(encoding="utf-8"))
    record = json.loads(content)
    if not isinstance(record, dict):
        raise ValueError(f"Run record must be a JSON object: {folder / 'record.json'}")
    record.setdefault("schema_version", 1)
    return RunRecord.model_validate(record).model_dump(mode="json")


def load_run(path: str | Path) -> dict:
    folder = Path(path)
    return {
        "path": str(folder.resolve()),
        "config": resolve_config(folder / "config.json"),
        "record": read_record(folder),
        "summary": json.loads((folder / "summary.json").read_text())
        if (folder / "summary.json").exists()
        else {},
        "observables": read_observables(folder),
    }


def read_observables(folder: Path, max_points: int | None = 2000) -> list[dict]:
    path = folder / "observables.csv"
    if not path.exists():
        return []
    if max_points is not None and max_points < 2:
        raise ValueError("max_points must be at least two")
    with path.open(encoding="utf-8", newline="") as source:
        count = max(0, sum(1 for _ in source) - 1)
    selected = (
        None
        if max_points is None or count <= max_points
        else set(np.rint(np.linspace(0, count - 1, max_points)).astype(int).tolist())
    )
    with path.open(newline="", encoding="utf-8") as source:
        return [
            {key: None if value == "" else float(value) for key, value in row.items()}
            for index, row in enumerate(csv.DictReader(source))
            if selected is None or index in selected
        ]


def read_frame(folder: Path, index: int, max_axis: int = 256) -> dict:
    from .model import make_grid
    from .observables import measure, measurement_validity

    config = resolve_config(folder / "config.json")
    grid = make_grid(config.grid)
    with h5py.File(folder / "state.h5", "r") as store:
        if index < 0 or index >= len(store["time"]):
            raise IndexError("frame index outside saved snapshots")
        psi, V, W, t = (
            store["psi"][index],
            store["potential"][:],
            store["absorber"][:],
            float(store["time"][index]),
        )
        initial_norm = float(store.attrs.get("initial_norm", 1.0))
        saved = (
            json.loads(store["diagnostics_json"][index]) if "diagnostics_json" in store else None
        )
        if saved and "observables" in saved:
            metrics, validity = saved["observables"], saved["validity"]
        else:
            metrics = saved or measure(
                psi, grid, V, kinetic=config.solver.kinetic, W=W, initial_norm=initial_norm
            )
            validity = measurement_validity(psi, grid, initial_norm)
        screen = None
        if "screen_integral" in store:
            screen = {
                "x": float(store.attrs["screen_x"]),
                "requested_x": config.sampling.screen_x,
                "density_x": float(
                    store.attrs.get(
                        "screen_density_x",
                        store.attrs["screen_x"]
                        - (grid.spacing[0] / 2 if config.solver.kinetic == "fd2" else 0),
                    )
                ),
                "y": store["y"][:].tolist(),
                "time": t,
                "current_integral": store["screen_integral"][index].tolist(),
                "density": store["screen_density"][index].tolist(),
                "definition": "time-integrated signed probability current; not detector counts",
                "quadrature": "trapezoidal current at every numerical timestep",
            }
        if "density_scale_max" in store.attrs:
            maximum = float(store.attrs["density_scale_max"])
        else:
            maximum = max(
                float(np.max(np.abs(store["psi"][i]) ** 2)) for i in range(len(store["time"]))
            )
    record = read_record(folder)
    step = metrics.get("step")
    if step is None:
        step = config.n_steps if t == config.solver.duration else round(t / config.solver.dt)
    return frame_payload(
        psi,
        grid,
        V,
        t,
        metrics,
        int(step),
        config.n_steps,
        max_axis,
        kinetic=config.solver.kinetic,
        screen=screen,
        validity=validity,
        run_id=record["id"],
        config_sha256=config_fingerprint(config),
        density_scale_max=maximum,
        density_scale_scope="max_across_saved_frames",
    )


def analyse_run(path: str | Path) -> dict:
    run = load_run(path)
    return {
        "id": run["record"]["id"],
        "status": run["record"]["status"],
        "config": run["config"].model_dump(mode="json"),
        "summary": run["summary"],
        "observables": run["observables"],
    }


def compare_runs(paths: list[str | Path]) -> dict:
    runs = [analyse_run(path) for path in paths]
    return {
        "runs": runs,
        "all_completed": all(run["status"] == "completed" for run in runs),
        "note": "Descriptive comparison; equal grids alone do not establish equal Hamiltonians or continuum accuracy.",
    }
