"""Build static assets and record the exact sources used to produce them."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source_hashes() -> dict[str, str]:
    frontend = ROOT / "frontend"
    inputs = [
        path
        for path in frontend.iterdir()
        if path.is_file() and path.suffix in {".json", ".ts", ".html", ".md"}
    ]
    for name in ("src", "tests", "scripts", "public"):
        inputs.extend(
            path
            for path in (frontend / name).rglob("*")
            if path.is_file() and not {"artifacts", "__pycache__"}.intersection(path.parts)
        )
    inputs.append(Path(__file__))
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(inputs)
    }


def asset_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "build-manifest.json"
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--copy-only",
        action="store_true",
        help="copy an already built bundle only if its recorded sources still match",
    )
    options = parser.parse_args()
    source = ROOT / "frontend" / "dist"
    if options.copy_only:
        manifest_path = source / "build-manifest.json"
        if not manifest_path.is_file():
            raise SystemExit("No build provenance exists; rebuild without --copy-only")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("source_sha256") != source_hashes()
            or manifest.get("asset_sha256") != asset_hashes(source)
            or manifest.get("build_executed") is not True
        ):
            raise SystemExit(
                "The recorded frontend sources/assets changed; rebuild without --copy-only"
            )
    else:
        node = shutil.which("node")
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if not node or not npm:
            raise SystemExit("Node.js and npm are required to rebuild the frontend")
        cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
        command = [node, str(cli), "run", "build"] if cli.exists() else [npm, "run", "build"]
        before = source_hashes()
        subprocess.run(command, cwd=ROOT / "frontend", check=True)
        if before != source_hashes():
            raise SystemExit("Frontend sources changed during build; run the build again")
        manifest = {
            "schema_version": 1,
            "created_utc": datetime.now(UTC).isoformat(),
            "build_executed": True,
            "command": command,
            "node": subprocess.check_output([node, "--version"], text=True).strip(),
            "source_sha256": before,
            "asset_sha256": asset_hashes(source),
        }
        (source / "build-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    if not (source / "index.html").is_file():
        raise SystemExit("frontend/dist/index.html missing; run npm ci and rebuild")
    destination = ROOT / "src" / "wavepacket" / "web"
    destination.mkdir(parents=True, exist_ok=True)
    expected = (ROOT / "src" / "wavepacket" / "web").resolve()
    if destination.resolve() != expected or not expected.is_relative_to(ROOT.resolve()):
        raise SystemExit("Generated assets must remain inside src/wavepacket/web")
    for asset in source.rglob("*"):
        target = destination / asset.relative_to(source)
        if not target.resolve().is_relative_to(expected):
            raise SystemExit(f"Refusing to copy an asset outside the generated directory: {target}")
    for old in destination.rglob("*"):
        if old.is_file() and not (source / old.relative_to(destination)).is_file():
            if not old.resolve().is_relative_to(expected):
                raise SystemExit(
                    f"Refusing to delete an asset outside the generated directory: {old}"
                )
            old.unlink()
    shutil.copytree(source, destination, dirs_exist_ok=True)
    if asset_hashes(destination) != manifest["asset_sha256"]:
        raise SystemExit("Packaged asset hashes differ from the built frontend")
    print(f"Packaged browser assets and source provenance in {destination}")


if __name__ == "__main__":
    main()
