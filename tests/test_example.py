"""The example source folder builds clean with every adapter."""
from __future__ import annotations

import shutil
from pathlib import Path

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


def test_example_has_no_generated_or_local_files():
    names = {p.relative_to(EXAMPLE).as_posix() for p in EXAMPLE.rglob("*") if p.is_file()}
    assert "local/paths.env.example" in names
    assert "local/paths.env" not in names
    assert not any(n.startswith("dist/") for n in names)
