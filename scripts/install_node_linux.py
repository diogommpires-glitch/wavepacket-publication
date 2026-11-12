"""Install checksum-verified Node 24 in the Linux user's own tool directory."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def download(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def main() -> int:
    if sys.platform != "linux":
        raise SystemExit(
            "This installer is for Linux; Windows uses its existing Node installation."
        )
    machine = platform.machine()
    architecture = {"x86_64": "x64", "aarch64": "arm64"}.get(machine)
    if architecture is None:
        raise SystemExit(f"Unsupported Node architecture: {machine}")
    releases = json.loads(download("https://nodejs.org/dist/index.json"))
    release = next(row for row in releases if row["version"].startswith("v24.") and row["lts"])
    version = release["version"]
    filename = f"node-{version}-linux-{architecture}.tar.xz"
    base = f"https://nodejs.org/dist/{version}"
    checksums = download(f"{base}/SHASUMS256.txt").decode()
    expected = next(
        line.split()[0] for line in checksums.splitlines() if line.split()[-1] == filename
    )
    destination = Path.home() / ".local/share/wavepacket-node"
    target = destination / f"node-{version}-linux-{architecture}"
    if not target.exists():
        data = download(f"{base}/{filename}")
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise SystemExit(f"Node checksum mismatch: expected {expected}, got {actual}")
        destination.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=destination) as temporary:
            archive = Path(temporary) / filename
            archive.write_bytes(data)
            with tarfile.open(archive) as bundle:
                bundle.extractall(temporary, filter="data")
            staged = Path(temporary) / target.name
            (staged / "installation.json").write_text(
                json.dumps(
                    {
                        "source": f"{base}/{filename}",
                        "archive_sha256": actual,
                        "node_sha256": hashlib.sha256(
                            (staged / "bin/node").read_bytes()
                        ).hexdigest(),
                    },
                    indent=2,
                )
            )
            staged.replace(target)
    record = json.loads((target / "installation.json").read_text())
    if hashlib.sha256((target / "bin/node").read_bytes()).hexdigest() != record["node_sha256"]:
        raise SystemExit("Installed Node binary differs from its recorded checksum")
    actual_version = subprocess.check_output(
        [str(target / "bin/node"), "--version"], text=True
    ).strip()
    if actual_version != version:
        raise SystemExit(f"Expected {version}, got {actual_version}")
    current = destination / "current"
    if current.is_symlink():
        if not current.resolve().is_relative_to(destination.resolve()):
            raise SystemExit(f"Refusing to replace a foreign tool link: {current}")
        current.unlink()
    elif current.exists():
        raise SystemExit(f"Refusing to overwrite a directory: {current}")
    current.symlink_to(target, target_is_directory=True)
    profile = Path.home() / ".profile"
    marker = "# Wavepacket Lab Node 24"
    content = profile.read_text() if profile.exists() else ""
    if marker not in content:
        with profile.open("a") as stream:
            stream.write(
                f'\n{marker}\nexport PATH="$HOME/.local/share/wavepacket-node/current/bin:$PATH"\n'
            )
    print(target / "bin")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
