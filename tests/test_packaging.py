from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
NETWORK_HINTS = (
    "connection",
    "network",
    "temporary failure",
    "name resolution",
    "no matching distribution",
    "could not find a version",
    "could not fetch",
    "timed out",
    "proxy",
    "ssl",
)


def run(cmd, **kwargs):
    return subprocess.run(
        [str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        universal_newlines=True, timeout=600, **kwargs
    )


@pytest.mark.slow
def test_console_script_runs_in_clean_venv(tmp_path):
    # Install from a copy, so the build never writes into the working tree.
    project = tmp_path / "project"
    project.mkdir()
    shutil.copy(ROOT / "pyproject.toml", project / "pyproject.toml")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "agent_dotenv", project / "agent_dotenv", ignore=ignore)
    shutil.copytree(ROOT / "tests", project / "tests", ignore=ignore)

    venv = tmp_path / "venv"
    made = run([sys.executable, "-m", "venv", venv])
    if made.returncode != 0:
        pytest.skip("cannot create a virtual environment: %s" % made.stdout[-300:])
    folder = venv / ("Scripts" if (venv / "Scripts").is_dir() else "bin")
    python = folder / ("python.exe" if (folder / "python.exe").exists() else "python")

    installed = run([python, "-m", "pip", "install", "--disable-pip-version-check", project])
    if installed.returncode != 0:
        if any(hint in installed.stdout.lower() for hint in NETWORK_HINTS):
            pytest.skip("cannot install, probably offline: %s" % installed.stdout[-300:])
        pytest.fail("pip install failed:\n%s" % installed.stdout)

    script = next(folder.glob("agent-dotenv*"))
    result = run([script, "--help"], cwd=str(tmp_path))
    assert result.returncode == 0, result.stdout
    for command in ("init", "build", "doctor"):
        assert command in result.stdout

    module = run([python, "-m", "agent_dotenv", "--help"], cwd=str(tmp_path))
    assert module.returncode == 0, module.stdout

    # The package list must not include the tests folder.
    leak = run([python, "-c", "import tests"], cwd=str(tmp_path))
    assert leak.returncode != 0
