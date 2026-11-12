"""Inspectable reports generated from saved artifacts, without rerunning physics."""

from __future__ import annotations

import base64
import csv
import html
import json
from pathlib import Path

import h5py
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def report_run(folder: str | Path) -> Path:
    from .runner import read_observables

    folder = Path(folder)
    config = json.loads((folder / "config.json").read_text())
    summary = json.loads((folder / "summary.json").read_text())
    rows = read_observables(folder)
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    screen_image = ""
    with h5py.File(folder / "state.h5", "r") as store:
        if not len(store["time"]):
            raise ValueError("No saved snapshots to report")
        psi, initial = store["psi"][-1], store["psi"][0]
        x, V = store["x"][:], store["potential"][:]
        if psi.ndim == 1:
            fig, ax = plt.subplots(figsize=(9, 3.7), layout="constrained")
            ax.plot(x, np.abs(initial) ** 2, color="#97a6b4", label="Initial density")
            ax.plot(x, np.abs(psi) ** 2, color="#168d9e", label="Final density")
            ax.set(xlabel="x [dimensionless]", ylabel="Probability density", title=config["name"])
            if np.max(np.abs(V)) > 0:
                twin = ax.twinx()
                twin.plot(x, V, color="#bd7751", alpha=0.55, label="Potential")
                twin.set_ylabel("V [dimensionless]")
            ax.legend(frameon=False)
        else:
            y = store["y"][:]
            dx, dy = x[1] - x[0], y[1] - y[0]
            extent = (x[0] - dx / 2, x[-1] + dx / 2, y[0] - dy / 2, y[-1] + dy / 2)
            shared_max = float(
                store.attrs.get(
                    "density_scale_max",
                    max(float(np.max(np.abs(initial) ** 2)), float(np.max(np.abs(psi) ** 2))),
                )
            )
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.7), layout="constrained")
            for ax, state, title in zip(
                axes, (initial, psi), ("Initial density", "Final density"), strict=True
            ):
                image = ax.imshow(
                    np.abs(state) ** 2,
                    origin="lower",
                    extent=extent,
                    cmap="magma",
                    aspect="equal",
                    vmin=0,
                    vmax=shared_max,
                )
                ax.set(xlabel="x [dimensionless]", ylabel="y [dimensionless]", title=title)
                fig.colorbar(image, ax=ax, shrink=0.8)
        fig.savefig(folder / "density.png", dpi=150)
        plt.close(fig)
        if "screen_integral" in store:
            screen_y = store["y"][:]
            integral, density = store["screen_integral"][-1], store["screen_density"][-1]
            flux_x = float(store.attrs["screen_x"])
            density_x = float(store.attrs.get("screen_density_x", flux_x))
            final_time = float(store["time"][-1])
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.2), layout="constrained")
            axes[0].plot(screen_y, integral, color="#168d9e")
            axes[0].axhline(0, color="#97a6b4", linewidth=0.6)
            axes[0].set(
                xlabel="y [dimensionless]",
                ylabel="Signed integral of j_x dt",
                title=f"Current plane x={flux_x:g}",
            )
            axes[1].plot(screen_y, density, color="#bd7751")
            axes[1].set(
                xlabel="y [dimensionless]",
                ylabel="Instantaneous probability density",
                title=f"Density node x={density_x:g}, t={final_time:g}",
            )
            fig.savefig(folder / "screen.png", dpi=150)
            plt.close(fig)
            with (folder / "screen.csv").open("w", newline="", encoding="utf-8") as screen_stream:
                writer = csv.writer(screen_stream)
                writer.writerow(["y", "current_integral", "density", "flux_x", "density_x", "time"])
                for yy, flux, rho in zip(screen_y, integral, density, strict=True):
                    writer.writerow([yy, flux, rho, flux_x, density_x, final_time])
    fig, axes = plt.subplots(1, 2, figsize=(9, 3), layout="constrained")
    if rows:
        times = [r["time"] for r in rows]
        axes[0].plot(times, [r["norm"] for r in rows], color="#168d9e")
        energy_key = next(
            (key for key in ("energy", "energy_mean", "energy_conditional") if key in rows[0]), None
        )
        if energy_key:
            axes[1].plot(times, [r[energy_key] for r in rows], color="#bd7751")
        axes[1].set_ylabel(energy_key or "Energy unavailable")
    axes[0].set(xlabel="t [dimensionless]", ylabel="Surviving norm")
    axes[1].set_xlabel("t [dimensionless]")
    fig.savefig(folder / "diagnostics.png", dpi=150)
    plt.close(fig)

    def embedded(name: str) -> str:
        return "data:image/png;base64," + base64.b64encode((folder / name).read_bytes()).decode()

    if (folder / "screen.png").is_file():
        screen_image = f'<h2>Screen diagnostics</h2><img alt="Signed current integral and separate instantaneous density" src="{embedded("screen.png")}"><p>The current integral retains its sign. It is not a general detector-count distribution. Current-face and density-node positions are recorded separately.</p>'
    esc = html.escape
    warnings = "".join(f"<li>{esc(w)}</li>" for w in summary.get("warnings", []))
    result = f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(config["name"])} | Wavepacket report</title>
<style>body{{font:16px/1.65 system-ui;margin:40px auto;padding:0 24px;max-width:1000px;color:#203445;background:#fbfcfd}}h1{{font-size:36px}}h2{{margin-top:36px}}img{{width:100%;height:auto}}pre{{white-space:pre-wrap;background:#edf2f5;padding:20px;border-radius:8px;font-size:13px}}small{{color:#526675}}a{{color:#007a8c}}.status{{color:#007a8c;font-weight:600}}</style>
<small>WAVEPACKET / REPRODUCIBLE RUN REPORT</small><h1>{esc(config["name"])}</h1>
<p class="status">Scientific status: {esc(summary.get("scientific_status", summary["status"]))}</p>
<p>This report is generated during finalization. The canonical <code>record.json</code> determines whether finalization completed successfully. Conditional statistics below the reporting floor are withheld as null; curves leave gaps at those samples.</p>
<p>Single-particle, linear TDSE; static potential; numerical units hbar = m = 1. The numerical grid is periodic. Absorbing layers approximate open boundaries where enabled.</p>
<img alt="Initial and final probability density" src="{embedded("density.png")}">
<h2>Diagnostics</h2><img alt="Norm and energy diagnostics" src="{embedded("diagnostics.png")}">
{screen_image}
<h2>Scientific interpretation</h2><ul>{warnings}</ul>
<p>Screen current is a diagnostic, not a general detector-count model. Raw and phase-aligned errors require a declared reference. A conservation check alone does not establish physical accuracy.</p>
<h2>Summary</h2><pre>{esc(json.dumps(summary, indent=2))}</pre>
<h2>Resolved configuration</h2><pre>{esc(json.dumps(config, indent=2))}</pre>
<p>Reproduce with <code>wavepacket run config.json</code>. Read <code>manifest.json</code> for exact versions, provenance and artifact hashes.</p></html>"""
    path = folder / "report.html"
    path.write_text(result, encoding="utf-8")
    return path
