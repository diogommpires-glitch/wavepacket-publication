"""Set numerical threads before importing the frozen scientific study runners."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

for variable in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ[variable] = "1"

from wavepacket.studies import run_accuracy_cost, run_tunnelling  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", choices=["accuracy-cost", "tunnelling"])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    directory = args.output or Path("results/studies") / args.study
    report = (run_accuracy_cost if args.study == "accuracy-cost" else run_tunnelling)(directory)
    print(f"{report['study']}: {report['status']}; protocol {report['protocol_sha256']}")
    return 0 if report["status"] == "measured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
