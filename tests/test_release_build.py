"""A copied frontend bundle must retain evidence for its actual source inputs."""

import json
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from scripts import build_frontend


def test_source_archive_selects_project_inputs_without_vcs_ignores(tmp_path):
    root = Path(__file__).resolve().parents[1]
    project = tmp_path / "project"
    project.mkdir()
    configuration = (root / "pyproject.toml").read_text(encoding="utf-8")
    # Disable ancestor VCS metadata while preserving the real source-selection rules.
    (project / "pyproject.toml").write_text(
        configuration + "\n[tool.hatch.build]\nignore-vcs = true\n", encoding="utf-8"
    )
    expected = {
        "README.md": b"# Project\n",
        "LICENSE": b"Project license\n",
        "Start-Wavepacket.cmd": b"@echo off\n",
        "scripts/check.py": b"print('project check')\n",
        "src/wavepacket/__init__.py": b"",
        "frontend/public/fonts/example.ttf": b"\x00font fixture\xff",
    }
    unwanted = [
        f"{directory}/{name}"
        for directory in ("frontend/node_modules/dependency", ".venv/dependency", ".refine")
        for name in ("README.md", "LICENSE", "scripts/check.py")
    ]
    unwanted += [
        "AGENTS.md",
        "Start-Lab.cmd",
        "CLAUDE.md",
        "ROADMAP.md",
        "docs/usage.md",
        ".hallmark/log.json",
        "results/validation/full/validation.json",
    ]
    fixtures = {**expected, **dict.fromkeys(unwanted, b"Dependency/runtime input\n")}
    for name, content in fixtures.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "sdist", "-d", str(tmp_path)],
        cwd=project,
        check=True,
    )
    with tarfile.open(next(tmp_path.glob("*.tar.gz"))) as archive:
        members = {
            member.name.partition("/")[2]: member
            for member in archive.getmembers()
            if member.isfile()
        }
        assert expected.keys() <= members.keys(), sorted(expected.keys() - members.keys())
        assert not set(unwanted).intersection(members), sorted(set(unwanted).intersection(members))
        for name, content in expected.items():
            stream = archive.extractfile(members[name])
            assert stream is not None
            assert stream.read() == content, name


def test_source_archive_preserves_every_public_frontend_asset(tmp_path):
    root = Path(__file__).resolve().parents[1]
    expected = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in (root / "frontend/public").rglob("*")
        if path.is_file()
    }
    assert expected
    subprocess.run(
        [sys.executable, "-m", "hatchling", "build", "-t", "sdist", "-d", str(tmp_path)],
        cwd=root,
        check=True,
    )
    source = next(tmp_path.glob("*.tar.gz"))
    with tarfile.open(source) as archive:
        members = {
            member.name.partition("/")[2]: member
            for member in archive.getmembers()
            if member.isfile()
        }
        assert expected.keys() <= members.keys(), sorted(expected.keys() - members.keys())
        for name, content in expected.items():
            stream = archive.extractfile(members[name])
            assert stream is not None
            assert stream.read() == content, name


@pytest.mark.parametrize("changed", ["source", "asset"])
def test_copy_only_rejects_a_stale_bundle_before_packaging(tmp_path, monkeypatch, changed):
    source = tmp_path / "frontend"
    (source / "src").mkdir(parents=True)
    (source / "src/main.ts").write_text("const source = 1;", encoding="utf-8")
    (source / "package.json").write_text("{}", encoding="utf-8")
    (source / "dist").mkdir()
    (source / "dist/index.html").write_text("<html>bundle</html>", encoding="utf-8")
    script = tmp_path / "scripts/build_frontend.py"
    script.parent.mkdir()
    script.write_text("build input", encoding="utf-8")
    monkeypatch.setattr(build_frontend, "ROOT", tmp_path)
    monkeypatch.setattr(build_frontend, "__file__", str(script))
    manifest = {
        "build_executed": True,
        "source_sha256": build_frontend.source_hashes(),
        "asset_sha256": build_frontend.asset_hashes(source / "dist"),
    }
    (source / "dist/build-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    target = source / ("src/main.ts" if changed == "source" else "dist/index.html")
    target.write_text("changed after the original build", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", [str(script), "--copy-only"])
    with pytest.raises(SystemExit, match="sources/assets changed"):
        build_frontend.main()
    assert not (tmp_path / "src/wavepacket/web").exists()
