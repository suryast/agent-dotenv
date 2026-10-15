"""Repository gates: neutral core, no private names, README About line."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "agent_dotenv"
ABOUT = (
    "Write your agent rules, identity and skills once. "
    "Build them for any coding agent: AGENTS.md, Claude Code, Cursor and more. "
    "Layered, secret-safe, standard library only."
)

# Words are built from fragments so that this file does not match its own scan.
HARNESS_WORDS = ("clau" + "de", "cur" + "sor", "agents" + ".md")
EMPLOYER = "hire" + "up"
EMPLOYER_DOMAIN = EMPLOYER + ".com.au"
PERSONAL_PATTERNS = (re.compile(r"/Users/[A-Za-z0-9._-]+"), re.compile(r"/home/[A-Za-z0-9._-]+/"))

SKIP_DIRS = {
    ".git",
    ".superpowers",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
}
SKIP_PREFIXES = ("tests/fixtures", "docs/superpowers")


def _repo_files() -> List[Path]:
    """Text files of the repository, without build output, caches and the skipped folders."""
    found: List[Path] = []
    for dirpath, dirs, names in os.walk(str(ROOT)):
        rel_dir = Path(dirpath).relative_to(ROOT).as_posix()
        dirs[:] = sorted(
            d
            for d in dirs
            if d not in SKIP_DIRS
            and not d.endswith(".egg-info")
            and not (rel_dir + "/" + d if rel_dir != "." else d).startswith(SKIP_PREFIXES)
        )
        for name in sorted(names):
            if name == ".git":  # a linked worktree has a .git file that holds a local path
                continue
            path = Path(dirpath) / name
            try:
                path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary files
            found.append(path)
    return found


def test_core_has_no_harness_name():
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        if "adapters" in path.relative_to(CORE).parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for word in HARNESS_WORDS:
            if word in text:
                offenders.append("%s: %s" % (path.relative_to(ROOT), word))
    assert not offenders, "core files name a harness: %s" % "; ".join(offenders)


def test_repo_has_no_employer_or_personal_names():
    offenders = []
    for path in _repo_files():
        lowered = path.read_text(encoding="utf-8").lower()
        for word in (EMPLOYER, EMPLOYER_DOMAIN):
            if word in lowered:
                offenders.append("%s: contains the employer name" % path.relative_to(ROOT))
                break
        text = path.read_text(encoding="utf-8")
        for pattern in PERSONAL_PATTERNS:
            if pattern.search(text):
                offenders.append("%s: contains a home directory path" % path.relative_to(ROOT))
                break
    assert not offenders, "; ".join(sorted(set(offenders)))


def test_gate_scans_the_docs_and_example():
    # Guards the gate itself: the scan must reach the files that hold public text.
    scanned = {p.relative_to(ROOT).as_posix() for p in _repo_files()}
    for expected in (
        "README.md",
        "CLAUDE.md",
        "docs/adapters.md",
        "docs/security.md",
        "examples/minimal/adapters/plain_text.py",
        "examples/minimal/base/rules.md",
        "agent_dotenv/templates.py",
    ):
        assert expected in scanned, "%s is not scanned" % expected
    assert not any(s.startswith("docs/superpowers") for s in scanned)


def test_readme_first_line_is_the_about_sentence():
    lines = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    assert lines[0] == "# agent-dotenv"
    content = [line for line in lines[1:] if line.strip()]
    assert content[0] == ABOUT
