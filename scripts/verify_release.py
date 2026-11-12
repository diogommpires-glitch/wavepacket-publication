"""Execute release gates against fresh notebooks, assets and an isolated wheel install."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import tomllib
import uuid
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

from build_frontend import asset_hashes, source_hashes

ROOT = Path(__file__).resolve().parents[1]
SCIENCE_SOURCES = {
    "config.py",
    "model.py",
    "operators.py",
    "propagators.py",
    "observables.py",
    "experiments.py",
    "validation.py",
    "units.py",
}

WHEEL_PROBE = r"""
import hashlib, importlib.metadata, json, sys, zipfile
from pathlib import Path
import wavepacket
from fastapi.testclient import TestClient
from wavepacket.api import create_app
wheel, environment, data, version, suite = map(str, sys.argv[1:])
module = Path(wavepacket.__file__).resolve()
assert module.is_relative_to(Path(environment).resolve()), module
assert wavepacket.__version__ == importlib.metadata.version('wavepacket-lab') == version
verified = {}
with zipfile.ZipFile(wheel) as archive:
    for name in archive.namelist():
        if name.startswith('wavepacket/') and not name.endswith('/'):
            installed = module.parent.parent / name
            digest = hashlib.sha256(archive.read(name)).hexdigest()
            assert installed.is_file() and hashlib.sha256(installed.read_bytes()).hexdigest() == digest, name
            verified[name] = digest
report_path = Path(data) / 'results' / 'validation' / suite / 'validation.json'
report = json.loads(report_path.read_text(encoding='utf-8'))
report_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
assert report['suite'] == suite and report['status'] == 'passed'
with TestClient(create_app(data_dir=Path(data)), base_url='http://127.0.0.1') as client:
    evidence = client.get('/api/validation', params={'suite': suite}).json()
    assert evidence['status'] == 'passed' and evidence['freshness']['source_match'] is True, evidence
    assert evidence['freshness']['report_sha256'] == report_hash
    assert Path(evidence['freshness']['evidence_path']).resolve() == report_path.resolve()
    assert client.get('/').status_code == 200
    runs = client.get('/api/runs').json()
    assert len(runs) == 1 and runs[0]['status'] == 'completed', runs
    frame = client.get('/api/runs/' + runs[0]['id'] + '/frames/2').json()
    assert frame['run_id'] == runs[0]['id'] and abs(frame['observables']['norm'] - 1) < 1e-10
print(json.dumps({'module':str(module),'version':version,'verified_installed_files':verified,
                  'validation_report_sha256':report_hash,'validation_suite':suite,
                  'run_id':runs[0]['id']}, indent=2))
"""


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def engine_hashes() -> dict[str, str]:
    return {path.name: digest(path) for path in sorted((ROOT / "src/wavepacket").glob("*.py"))}


def inspect_studies(root: Path) -> dict:
    from wavepacket.config import SimulationConfig, config_fingerprint
    from wavepacket.studies import (
        THREAD_VARIABLES,
        accuracy_cost_protocol,
        target_attainment,
        tunnelling_protocol,
    )

    required = SCIENCE_SOURCES | {"studies.py"}
    verified = {}
    for name, protocol_builder in (
        ("accuracy-cost", accuracy_cost_protocol),
        ("tunnelling", tunnelling_protocol),
    ):
        directory = root / "results/studies" / name
        protocol = json.loads((directory / "protocol.json").read_text(encoding="utf-8"))
        canonical = json.dumps(protocol, sort_keys=True, separators=(",", ":"), allow_nan=False)
        protocol_hash = hashlib.sha256(canonical.encode()).hexdigest()
        report_path = directory / "results.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        provenance = report["provenance"]
        sources = provenance["source_sha256"]
        if (
            protocol != protocol_builder()
            or (directory / "protocol.sha256").read_text().strip() != protocol_hash
            or report["protocol_sha256"] != protocol_hash
            or report["study"] != name
            or report["status"] != "measured"
            or any(report["environment"]["threads"].get(key) != "1" for key in THREAD_VARIABLES)
            or required - sources.keys()
            or sources != provenance["source_sha256_at_start"]
            or provenance["sources_changed_during_run"]
            or any(
                digest(root / "src/wavepacket" / source) != value
                for source, value in sources.items()
            )
        ):
            raise ValueError(f"Canonical {name} study is incomplete, invalidated or stale")
        if name == "accuracy-cost":
            if [panel["id"] for panel in report["panels"]] != [
                panel["id"] for panel in protocol["panels"]
            ]:
                raise ValueError("Accuracy/cost panels do not match the frozen protocol")
            for panel, expected in zip(report["panels"], protocol["panels"], strict=True):
                measurements = panel["measurements"]
                expected_configs = set()
                for method in expected["methods"]:
                    for dt in expected["timesteps"]:
                        data = json.loads(json.dumps(expected["config"]))
                        data["solver"].update(method=method, dt=dt)
                        expected_configs.add(
                            config_fingerprint(SimulationConfig.model_validate(data))
                        )
                recorded_configs = [row["configuration_sha256"] for row in measurements]
                if len(measurements) != len(expected["methods"]) * len(
                    expected["timesteps"]
                ) or any(len(row["warm_timings"]) != protocol["repeats"] for row in measurements):
                    raise ValueError("Accuracy/cost repeated measurements are incomplete")
                if (
                    len(set(recorded_configs)) != len(recorded_configs)
                    or set(recorded_configs) != expected_configs
                    or any(
                        config_fingerprint(SimulationConfig.model_validate(row["config"]))
                        != row["configuration_sha256"]
                        or row["method"] != row["config"]["solver"]["method"]
                        or row["dt"] != row["config"]["solver"]["dt"]
                        for row in measurements
                    )
                    or panel["target_attainment"]
                    != target_attainment(measurements, protocol["accuracy_targets_raw_l2"])
                ):
                    raise ValueError(
                        "Accuracy/cost case identities or target outcomes do not match the protocol"
                    )
        else:
            packets = report["packets"]
            expected_packets = {
                (k, sigma)
                for k in protocol["momentum_centers"]
                for sigma in protocol["density_sigma"]
            }
            if (
                len(packets) != len(expected_packets)
                or {(row["momentum"], row["sigma"]) for row in packets} != expected_packets
                or len(report["refinement"]) != 3
                or {row["axis"] for row in report["refinement"]} != {"space", "time", "domain"}
            ):
                raise ValueError("Tunnelling packets or refinements are incomplete")
        verified[name] = {
            "protocol_sha256": protocol_hash,
            "report_sha256": digest(report_path),
            "source_sha256": sources,
            "status": report["status"],
        }
    return verified


def notebook_source_hash(path: Path) -> str:
    book = json.loads(path.read_text(encoding="utf-8"))
    cells = [
        {
            "cell_type": cell["cell_type"],
            "source": "".join(cell["source"])
            if isinstance(cell["source"], list)
            else cell["source"],
        }
        for cell in book["cells"]
    ]
    return hashlib.sha256(json.dumps(cells, sort_keys=True).encode()).hexdigest()


def inspect_packages(wheel: Path, source: Path, version: str) -> dict:
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        metadata = next(name for name in names if name.endswith(".dist-info/METADATA"))
        identity = BytesParser().parsebytes(archive.read(metadata))
        if identity["Version"] != version or identity["Name"] != "wavepacket-lab":
            raise ValueError("Fresh wheel identity differs from pyproject.toml")
        package_hashes = {
            name: hashlib.sha256(archive.read(name)).hexdigest()
            for name in names
            if name.startswith("wavepacket/") and not name.endswith("/")
        }
        for name, expected in package_hashes.items():
            if digest(ROOT / "src" / name) != expected:
                raise ValueError(f"Wheel content differs from current source: {name}")
        manifest = json.loads(archive.read("wavepacket/web/build-manifest.json"))
        if manifest["source_sha256"] != source_hashes() or manifest["build_executed"] is not True:
            raise ValueError("Wheel frontend provenance does not match current sources")
        assets = {
            name.removeprefix("wavepacket/web/"): value
            for name, value in package_hashes.items()
            if name.startswith("wavepacket/web/") and not name.endswith("build-manifest.json")
        }
        if assets != manifest["asset_sha256"] or assets != asset_hashes(ROOT / "frontend/dist"):
            raise ValueError("Wheel assets do not match the freshly built frontend")
        if "index.html" not in assets or not any(name.endswith(".js") for name in assets):
            raise ValueError("Wheel is missing the laboratory HTML or JavaScript bundle")
    required = {
        "pyproject.toml",
        "requirements-lock.txt",
        "README.md",
        "LICENSE",
        "scripts/verify_release.py",
        "scripts/build_frontend.py",
        "scripts/execute_notebooks.py",
        "scripts/setup_linux.sh",
        "scripts/setup.ps1",
        ".github/workflows/ci.yml",
        "tests/test_api.py",
    }
    required.update(source_hashes())
    forbidden_parts = {
        ".git",
        ".hallmark",
        ".refine",
        ".venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".ipynb_checkpoints",
        ".runtime",
        ".ipython",
        ".jupyter",
        "runs",
        "results",
    }
    secret = re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bgh[pousr]_[A-Za-z0-9]{30,}\b"
    )
    with tarfile.open(source) as archive:
        files = {}
        for member in archive.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or member.issym() or member.islnk():
                raise ValueError(f"Unsafe source archive member: {member.name}")
            relative = PurePosixPath(*name.parts[1:])
            if (
                forbidden_parts.intersection(relative.parts)
                or relative.suffix in {".pyc", ".tsbuildinfo", ".pem", ".key"}
                or relative.name.startswith(".env")
            ):
                raise ValueError(f"Cache, runtime or secret file in source archive: {relative}")
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable source archive member: {relative}")
            content = stream.read()
            if secret.search(content):
                raise ValueError(f"Credential pattern in source archive: {relative}")
            files[str(relative)] = hashlib.sha256(content).hexdigest()
        missing = sorted(required - files.keys())
        if missing:
            raise ValueError(f"Source archive is missing runnable inputs: {missing}")
        for name in required:
            if files[name] != digest(ROOT / name):
                raise ValueError(f"Source archive input differs from current source: {name}")
    return {
        "wheel": str(wheel.relative_to(ROOT)),
        "source": str(source.relative_to(ROOT)),
        "wheel_sha256": digest(wheel),
        "source_sha256": digest(source),
        "wheel_files": len(package_hashes),
        "source_files": len(files),
        "archive_audit": "Required runnable inputs and declared cache/credential patterns checked; not a general secret guarantee.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", action="store_true", help="run browser workflows against an isolated API"
    )
    parser.add_argument(
        "--evidence-suite",
        choices=("quick", "full"),
        default="quick",
        help="scientific suite executed through the freshly installed CLI (default: quick)",
    )
    args = parser.parse_args()
    attempt = uuid.uuid4().hex
    destination = ROOT / "results/release" / attempt
    work = ROOT / "tmp/release-verification" / attempt
    destination.mkdir(parents=True)
    work.mkdir(parents=True)
    started_sources = engine_hashes()
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]
    results = []

    def record(name: str, passed: bool, **detail) -> bool:
        results.append({"name": name, "passed": passed, **detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)
        return passed

    def run(name: str, command: list[str], *, cwd: Path = ROOT, timeout: int = 1800) -> bool:
        try:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
            output, return_code = completed.stdout + completed.stderr, completed.returncode
        except (OSError, subprocess.TimeoutExpired) as error:
            output, return_code = f"{type(error).__name__}: {error}", -1
        log = destination / f"{name}.txt"
        log.write_text(output, encoding="utf-8")
        return record(
            name,
            return_code == 0,
            command=command,
            cwd=str(cwd),
            log=str(log.relative_to(ROOT)),
            return_code=return_code,
        )

    def check(name: str, function) -> bool:
        try:
            return record(name, True, **function())
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            zipfile.BadZipFile,
            tarfile.TarError,
        ) as error:
            return record(name, False, error=f"{type(error).__name__}: {error}")

    run("pytest", [sys.executable, "-m", "pytest", "--basetemp", str(work / "pytest"), "-q"])
    run("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
    run("mypy", [sys.executable, "-m", "mypy", "src/wavepacket"])
    node, npm = shutil.which("node"), shutil.which("npm.cmd") or shutil.which("npm")
    if node and npm:
        npm_cli = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        npm_command = [node, str(npm_cli)] if npm_cli.is_file() else [npm]
        for script in ("check:api", "typecheck", "lint", "test"):
            run(
                "frontend-" + script.replace(":", "-"),
                [*npm_command, "run", script],
                cwd=ROOT / "frontend",
            )
    else:
        record("frontend-tools", False, error="Node.js/npm unavailable")
    built = run("frontend-build", [sys.executable, "scripts/build_frontend.py"])
    executed = run("notebooks-execute", [sys.executable, "scripts/execute_notebooks.py"])

    def notebooks():
        books = json.loads(
            (ROOT / "results/notebook_runs/execution_summary.json").read_text(encoding="utf-8")
        )
        if not executed or len(books) != 4:
            raise ValueError("This invocation did not execute all four notebooks successfully")
        for book in books:
            source = ROOT / "notebooks" / book["notebook"]
            output = Path(book["output"])
            if (
                book["status"] != "executed"
                or book["error_outputs"] != 0
                or book["source_sha256"] != notebook_source_hash(source)
                or book["executed_source_sha256"] != book["source_sha256"]
                or book["executed_notebook_sha256"] != digest(output)
                or book["engine_source_sha256"] != engine_hashes()
                or book["engine_changed_during_execution"]
            ):
                raise ValueError(f"Notebook output/source freshness failed: {book['notebook']}")
        return {"notebooks": books}

    check("notebooks-source-and-output-match", notebooks)

    def science():
        path = ROOT / "results/validation/full/validation.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        recorded = report["provenance"]["source_sha256"]
        if (
            report["suite"] != "full"
            or report["status"] != "passed"
            or SCIENCE_SOURCES - recorded.keys()
            or any(engine_hashes().get(name) != value for name, value in recorded.items())
            or report["provenance"]["sources_changed_during_run"]
        ):
            raise ValueError(
                "The saved full scientific report is failed, incomplete or stale against current sources"
            )
        return {
            "report_sha256": digest(path),
            "summary": report["summary"],
            "source_sha256": recorded,
        }

    check("science-evidence-source-match", science)
    check("canonical-studies-source-and-protocol-match", lambda: inspect_studies(ROOT))
    packages = run(
        "packages-build",
        [sys.executable, "-m", "build", "--no-isolation", "--outdir", str(work / "dist")],
    )
    wheels, sources = list((work / "dist").glob("*.whl")), list((work / "dist").glob("*.tar.gz"))
    if packages and built and len(wheels) == len(sources) == 1:
        wheel, source = wheels[0], sources[0]
        audited = check("package-contents", lambda: inspect_packages(wheel, source, version))
        environment = work / "wheel-venv"
        created = run(
            "wheel-environment",
            [
                sys.executable,
                "-m",
                "venv",
                "--system-site-packages",
                "--without-pip",
                str(environment),
            ],
        )
        executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if created and audited:
            # A nested venv's system-site-packages refers to the base interpreter,
            # not this invocation's venv. Share dependency directories explicitly;
            # importing and hashing the application inside the new env remains mandatory.
            dependencies = sorted({sysconfig.get_path("purelib"), sysconfig.get_path("platlib")})
            site = environment / (
                "Lib/site-packages"
                if os.name == "nt"
                else f"lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
            )
            (site / "verification-dependencies.pth").write_text(
                "\n".join(dependencies) + "\n", encoding="utf-8"
            )
            record(
                "wheel-shared-dependencies",
                True,
                directories=dependencies,
                scope="Dependencies are shared; the application must import from the new environment and match every wheel file.",
            )
            installed = run(
                "wheel-install",
                [
                    str(executable),
                    "-I",
                    "-m",
                    "pip",
                    "--disable-pip-version-check",
                    "install",
                    "--no-index",
                    "--no-deps",
                    "--force-reinstall",
                    str(wheel),
                ],
                cwd=work,
            )
            if installed:
                data = work / "installed-data"
                run(
                    "installed-cli-validation",
                    [
                        str(executable),
                        "-I",
                        "-m",
                        "wavepacket",
                        "validate",
                        "--suite",
                        args.evidence_suite,
                        "--data-dir",
                        str(data),
                    ],
                    cwd=work,
                )
                config = work / "smoke.json"
                config.write_text(
                    json.dumps(
                        {
                            "grid": {"points": [64]},
                            "solver": {"duration": 0.04},
                            "sampling": {"snapshots": 3},
                        }
                    ),
                    encoding="utf-8",
                )
                run(
                    "installed-cli-run",
                    [
                        str(executable),
                        "-I",
                        "-m",
                        "wavepacket",
                        "run",
                        str(config),
                        "--data-dir",
                        str(data),
                    ],
                    cwd=work,
                )
                run(
                    "installed-wheel-content-and-api",
                    [
                        str(executable),
                        "-I",
                        "-c",
                        WHEEL_PROBE,
                        str(wheel),
                        str(environment),
                        str(data),
                        version,
                        args.evidence_suite,
                    ],
                    cwd=work,
                )
    else:
        record(
            "package-contents",
            False,
            error="Fresh frontend or package build failed, or did not produce exactly one wheel and sdist",
        )
    if args.browser:
        run("browser", [sys.executable, "scripts/check_browser.py"])
    record(
        "source-stable-during-verification",
        started_sources == engine_hashes(),
        source_sha256=engine_hashes(),
        source_sha256_at_start=started_sources,
    )
    summary = {
        "created_utc": datetime.now(UTC).isoformat(),
        "attempt": attempt,
        "platform": platform.platform(),
        "python": sys.executable,
        "version": version,
        "status": "passed" if all(result["passed"] for result in results) else "failed",
        "checks": results,
        "linux_ci": "Not asserted by this local verification; inspect the actual hosted run.",
        "limitations": [
            "Fixed fixtures and checked workflows do not certify arbitrary user configurations.",
            "The isolated wheel environment shares dependency packages; installed application bytes are checked against the fresh wheel.",
            "Source archive checks cover required inputs and declared credential patterns, not all possible secrets.",
        ],
    }
    encoded = json.dumps(summary, indent=2) + "\n"
    (destination / "verification.json").write_text(encoded, encoding="utf-8")
    (ROOT / "results/release/verification.json").write_text(encoded, encoding="utf-8")
    print(summary["status"], flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
