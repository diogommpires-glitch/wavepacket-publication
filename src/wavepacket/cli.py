"""Reproducible studies and the local lab from one installed command."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

import typer

from .runner import estimate_resources, resolve_config, run_simulation
from .storage import RunBusy, StoragePaths

app = typer.Typer(no_args_is_help=True, help="Wavepacket: derive, simulate, validate, inspect.")


def emit(value):
    typer.echo(json.dumps(value, indent=2, default=str))


@app.command()
def doctor():
    """Print runtime, scientific dependency and unit-conversion information."""
    from .config import SimulationConfig
    from .runner import provenance

    emit(
        {
            "python": sys.executable,
            "platform": platform.platform(),
            "provenance": provenance(SimulationConfig()),
        }
    )


@app.command()
def run(
    config: Path,
    output: Path | None = None,
    estimate_only: bool = False,
    data_dir: Path | None = None,
):
    """Run a versioned JSON configuration without silently changing its settings."""
    if output is not None and data_dir is not None:
        raise typer.BadParameter(
            "--output is a legacy runs-root override; use either --output or --data-dir"
        )
    paths = StoragePaths.resolve(data_dir, runs_root=output)
    try:
        resolved = resolve_config(config)
        if estimate_only:
            emit(estimate_resources(resolved))
        else:
            emit(run_simulation(resolved, paths.runs))
    except (ValueError, OSError, FloatingPointError, RunBusy) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def experiment(
    name: str = "list",
    output: Path | None = None,
    config_only: bool = False,
    data_dir: Path | None = None,
):
    """List curated presets or run one by ID."""
    from .experiments import get_experiment, list_experiments

    if output is not None and data_dir is not None:
        raise typer.BadParameter(
            "--output is a legacy runs-root override; use either --output or --data-dir"
        )
    if name == "list":
        emit([{k: v for k, v in entry.items() if k != "config"} for entry in list_experiments()])
        return
    try:
        config = get_experiment(name)
    except (ValueError, KeyError) as exc:
        typer.echo(f"Unknown experiment: {name}", err=True)
        raise typer.Exit(1) from exc
    emit(
        config.model_dump(mode="json")
        if config_only
        else run_simulation(config, StoragePaths.resolve(data_dir, runs_root=output).runs)
    )


@app.command()
def validate(
    suite: str = "quick",
    output: Path | None = None,
    data_dir: Path | None = None,
    evidence_dir: Path | None = None,
):
    """Execute independent scientific acceptance checks and save their actual results."""
    from .validation import run_validation

    if suite not in ("quick", "full"):
        raise typer.BadParameter("suite must be quick or full")
    if output is not None and (data_dir is not None or evidence_dir is not None):
        raise typer.BadParameter(
            "--output is a legacy suite-directory override; use it alone, or use --data-dir/--evidence-dir"
        )
    paths = StoragePaths.resolve(data_dir, evidence_dir=evidence_dir)
    report = run_validation(
        suite=suite, output=output if output is not None else paths.evidence / suite
    )
    emit(report)
    if report.get("status") in ("failed", "fail") or report.get("passed") is False:
        raise typer.Exit(1)


@app.command()
def benchmark(output: Path | None = None, data_dir: Path | None = None):
    """Measure work versus error; no unmeasured speedup targets."""
    from .benchmarks import run_benchmarks

    if output is not None and data_dir is not None:
        raise typer.BadParameter("Use either --output or --data-dir")
    emit(
        run_benchmarks(
            output=output
            if output is not None
            else StoragePaths.resolve(data_dir).data_dir / "results" / "benchmarks"
        )
    )


@app.command()
def report(run: Path):
    """Regenerate an HTML report from saved scientific data."""
    from .reporting import report_run

    typer.echo(str(report_run(run)))


@app.command()
def serve(
    port: int = 8765,
    runs: Path | None = None,
    open_browser: bool = False,
    data_dir: Path | None = None,
    evidence_dir: Path | None = None,
):
    """Serve the packaged browser laboratory on loopback only."""
    import threading
    import webbrowser

    import uvicorn

    from .api import create_app

    if not 1024 <= port <= 65535:
        raise typer.BadParameter("port must be 1024..65535")
    if runs is not None and data_dir is not None:
        raise typer.BadParameter(
            "--runs is a legacy runs-root override; use either --runs or --data-dir"
        )
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
    uvicorn.run(
        create_app(runs, data_dir=data_dir, evidence_dir=evidence_dir),
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    app()
