"""Execute the four research notebooks with this exact Python interpreter.

The default preserves source notebooks and writes executed copies beneath
results/notebook_runs/executed. --in-place refreshes the release notebooks.
No user kernel registration or user-profile runtime directory is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import nbformat
from jupyter_client import KernelManager
from nbclient import NotebookClient


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in-place", action="store_true", help="refresh source notebooks instead of executed copies")
    parser.add_argument("--timeout", type=int, default=120, help="maximum seconds per code cell (default: 120)")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 600:
        parser.error("timeout must be between one and 600 seconds")
    root = Path(__file__).resolve().parents[1]
    output = root / "results" / "notebook_runs"
    for key, name in (("JUPYTER_RUNTIME_DIR", ".runtime"), ("IPYTHONDIR", ".ipython"),
                      ("JUPYTER_CONFIG_DIR", ".jupyter"), ("MPLCONFIGDIR", ".matplotlib")):
        location = output / name
        location.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(location)
    destination = root / "notebooks" if args.in_place else output / "executed"
    destination.mkdir(parents=True, exist_ok=True)
    files = sorted((root / "notebooks").glob("0*.ipynb"))
    if len(files) != 4:
        parser.error(f"expected four source notebooks, found {len(files)}")
    summary = []
    failed = False
    def sources_hash(book):
        sources = [{"cell_type": cell.cell_type, "source": cell.source} for cell in book.cells]
        return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()
    def engine_hashes():
        return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path in sorted((root / "src/wavepacket").glob("*.py"))}
    for path in files:
        started = time.perf_counter()
        book = nbformat.read(path, as_version=4)
        nbformat.validate(book)
        source_hash = sources_hash(book)
        engine_before = engine_hashes()
        client = NotebookClient(book, timeout=args.timeout, kernel_name="python3",
                                resources={"metadata": {"path": str(root)}})
        # The native kernel spec is changed in memory only. This launches the
        # active venv interpreter without installing a kernelspec in a profile.
        client.km = KernelManager(kernel_name="python3")
        client.km.kernel_spec.argv = [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"]
        record = {"notebook": path.name, "output": str(destination / path.name),
                  "python": sys.executable, "status": "executed", "source_sha256": source_hash,
                  "engine_source_sha256": engine_before}
        try:
            client.execute()
            nbformat.validate(book)
        except Exception as error:
            failed = True
            record.update(status="failed", error=f"{type(error).__name__}: {error}"[:2000])
        finally:
            nbformat.write(book, destination / path.name)
        record["executed_source_sha256"] = sources_hash(book)
        record["executed_notebook_sha256"] = hashlib.sha256((destination / path.name).read_bytes()).hexdigest()
        record["engine_changed_during_execution"] = engine_before != engine_hashes()
        if record["executed_source_sha256"] != source_hash or record["engine_changed_during_execution"]:
            failed = True
            record.update(status="failed", error="Notebook or engine source changed during execution")
        record["elapsed_seconds"] = time.perf_counter() - started
        record["code_cells"] = sum(cell.cell_type == "code" for cell in book.cells)
        record["error_outputs"] = sum(item.output_type == "error" for cell in book.cells
                                      if cell.cell_type == "code" for item in cell.outputs)
        summary.append(record)
        print(json.dumps(record), flush=True)
        (output / "execution_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if failed:
            break
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
