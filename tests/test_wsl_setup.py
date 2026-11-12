"""Exercise WSL catalogue text parsing in the shell used by the Windows launchers."""

import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 regression")
@pytest.mark.parametrize("script_name", ["setup_wsl.ps1", "bootstrap_wsl.ps1"])
def test_wsl_catalogue_cleaner_accepts_nul_and_normal_distribution_names(script_name):
    powershell = shutil.which("powershell.exe")
    assert powershell is not None, "The Windows launchers require Windows PowerShell"
    path = Path(__file__).resolve().parents[1] / "scripts" / script_name
    match = re.search(
        r"^\s*\$installed\s*=\s*(.+)$", path.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match is not None, f"No WSL catalogue assignment found in {path}"
    expression = match.group(1)
    command = "& wsl.exe --list --quiet"
    assert expression.count(command) == 1
    # Supply captured catalogue text directly; no installer or WSL command executes.
    expression = expression.replace(command, "$catalogue")
    fixtures = [
        ["Ubuntu-24.04", "Debian"],
        ["\x00".join("Ubuntu-24.04") + "\x00", "\x00".join("Debian") + "\x00"],
    ]
    fixture_data = base64.b64encode(json.dumps(fixtures).encode()).decode()
    code = f"""$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) {{ throw 'Expected Windows PowerShell 5.1' }}
$fixtures = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{fixture_data}')) | ConvertFrom-Json
foreach ($catalogue in $fixtures) {{
    $actual = {expression}
    $expected = "Ubuntu-24.04`nDebian"
    if ($actual -cne $expected) {{ throw 'Distribution catalogue text changed unexpectedly' }}
}}
Write-Output ('PowerShell ' + $PSVersionTable.PSVersion + ': two catalogue fixtures passed')
"""
    encoded = base64.b64encode(code.encode("utf-16-le")).decode()
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "two catalogue fixtures passed" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell 5.1 regression")
@pytest.mark.parametrize("operation", ["checkout", "playwright"])
def test_wsl_bootstrap_preserves_native_argv_with_spaces(tmp_path, operation):
    powershell = shutil.which("powershell.exe")
    assert powershell is not None
    script = Path(__file__).resolve().parents[1] / "scripts/bootstrap_wsl.ps1"
    lines = script.read_text(encoding="utf-8").splitlines()
    if operation == "checkout":
        line = next(
            line
            for line in lines
            if "bootstrap_linux.sh" in line or "git clone --no-hardlinks" in line
        )
    else:
        line = next(line for line in lines if "playwright/cli.js" in line)
    recorder = tmp_path / "record_native_argv.py"
    recorder.write_text("import json, sys\nprint(json.dumps(sys.argv[1:]))\n", encoding="utf-8")
    assert line.startswith("& wsl.exe ")
    command = line.replace("& wsl.exe", f"& '{sys.executable}' '{recorder}'", 1)
    source = "/mnt/c/Users/example/Project Folder/wavepacket-lab"
    home = "/home/example/Research Folder"
    target = f"{home}/src/wavepacket-lab"
    code = f"""$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) {{ throw 'Expected Windows PowerShell 5.1' }}
$Distribution = 'Ubuntu-24.04'
$mountedProject = '{source}'
$linuxHome = '{home}'
$linuxProject = '{target}'
{command}
"""
    encoded = base64.b64encode(code.encode("utf-16-le")).decode()
    result = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = ["--distribution", "Ubuntu-24.04"]
    if operation == "checkout":
        expected += ["--exec", "bash", f"{source}/scripts/bootstrap_linux.sh", source, target]
    else:
        expected += [
            "--user",
            "root",
            "--exec",
            f"{home}/.local/share/wavepacket-node/current/bin/node",
            f"{target}/frontend/node_modules/playwright/cli.js",
            "install-deps",
            "chromium",
        ]
    assert json.loads(result.stdout) == expected


@pytest.mark.skipif(sys.platform != "win32", reason="Actual Windows/WSL path boundary")
def test_wsl_bootstrap_resolves_windows_backslashes_without_shell_interpretation():
    wsl = shutil.which("wsl.exe")
    if wsl is None:
        pytest.skip("WSL is not installed")
    installed = subprocess.run([wsl, "--list", "--quiet"], capture_output=True, timeout=15)
    text = installed.stdout.decode(
        "utf-16-le" if b"\0" in installed.stdout else "utf-8", errors="replace"
    )
    if installed.returncode != 0 or "Ubuntu-24.04" not in text:
        pytest.skip("Local Ubuntu-24.04 is not installed")
    root = Path(__file__).resolve().parents[1]
    line = next(
        line
        for line in (root / "scripts/bootstrap_wsl.ps1").read_text().splitlines()
        if line.startswith("$mountedProject =")
    )
    code = f"""$ErrorActionPreference = 'Stop'
$Distribution = 'Ubuntu-24.04'
$projectRoot = '{root}'
{line}
if ($LASTEXITCODE -ne 0) {{ throw 'wslpath failed' }}
Write-Output $mountedProject
"""
    encoded = base64.b64encode(code.encode("utf-16-le")).decode()
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    expected = f"/mnt/{root.drive[0].lower()}/{root.as_posix()[3:]}"
    assert result.stdout.strip() == expected
