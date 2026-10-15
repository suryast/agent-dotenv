"""The example source folder builds clean with every adapter."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Set

from agent_dotenv.pipeline import run_build

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "minimal"


def test_example_builds_clean(tmp_path):
    source = tmp_path / "minimal"
    shutil.copytree(str(EXAMPLE), str(source))
    result = run_build(source, ["all"], {})
    assert result.ok, (result.errors, result.findings)
    assert not result.errors
    notes = source / "dist" / "plain-text" / "notes.txt"
    assert notes.is_file()
    rules = (source / "base" / "rules.md").read_text(encoding="utf-8").split("---\n", 2)[2]
    assert notes.read_text(encoding="utf-8").strip() == rules.strip()
    assert (source / "dist" / "agents-md" / "AGENTS.md").is_file()


def _committable_files() -> Set[str]:
    """Example files that git would commit: tracked files and files git does not ignore.

    A local build of the example writes the gitignored dist/; that is not a defect.
    Without git (an unpacked archive), the two gitignored paths are skipped instead."""
    root = EXAMPLE.parent.parent
    git = shutil.which("git")
    if git and (root / ".git").exists():
        out = subprocess.run(
            [git, "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z",
             "--", "examples/minimal"],
            capture_output=True, text=True, check=True,
        ).stdout
        prefix = "examples/minimal/"
        return {n[len(prefix):] for n in out.split("\0") if n.startswith(prefix)}
    names = {p.relative_to(EXAMPLE).as_posix() for p in EXAMPLE.rglob("*") if p.is_file()}
    return {n for n in names if not n.startswith("dist/") and n != "local/paths.env"}


def test_example_has_no_generated_or_local_files():
    names = _committable_files()
    assert "local/paths.env.example" in names
    assert "local/paths.env" not in names
    assert not any(n.startswith("dist/") for n in names)
    ignored = (EXAMPLE / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "dist/" in ignored and "local/paths.env" in ignored
