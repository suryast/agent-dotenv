"""Repository gates: neutral core, no private names, README About line."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

import pytest

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

# Used only when the folder is not a git checkout (for example an unpacked archive).
SKIP_DIRS = {
    ".git",
    ".superpowers",
    ".pytest_cache",
    ".tox",
    ".venv",
    "venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
}
SKIP_PREFIXES = ("tests/fixtures", "docs/superpowers")


def _tracked(root: Path) -> Optional[List[str]]:
    """Paths that git tracks under `root`, or None when `root` is not a git checkout."""
    git = shutil.which("git")
    if not git or not (root / ".git").exists():  # a linked worktree has a .git file
        return None
    proc = subprocess.run(
        [git, "-C", str(root), "ls-files", "-z"], capture_output=True, text=True
    )
    if proc.returncode != 0:
        return None
    return sorted(n for n in proc.stdout.split("\0") if n)


def _walked(root: Path) -> List[str]:
    """Paths under `root`, without virtual environments, build output, caches and tool folders."""
    found: List[str] = []
    for dirpath, dirs, names in os.walk(str(root)):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.endswith(".egg-info"))
        for name in sorted(names):
            if name == ".git":  # a linked worktree has a .git file that holds a local path
                continue
            found.append(name if rel_dir == "." else rel_dir + "/" + name)
    return found


def _repo_files(root: Path = ROOT) -> List[Path]:
    """Text files of the repository: the files git tracks, or a filtered walk without git."""
    rels = _tracked(root)
    if rels is None:
        rels = _walked(root)
    found: List[Path] = []
    for rel in rels:
        if rel.startswith(SKIP_PREFIXES):
            continue
        path = root / rel
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or deleted files
        found.append(path)
    return found


def _offenders(root: Path) -> List[str]:
    offenders = []
    for path in _repo_files(root):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for word in (EMPLOYER, EMPLOYER_DOMAIN):
            if word in lowered:
                offenders.append("%s: contains the employer name" % path.relative_to(root))
                break
        for pattern in PERSONAL_PATTERNS:
            if pattern.search(text):
                offenders.append("%s: contains a home directory path" % path.relative_to(root))
                break
    return sorted(set(offenders))


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
    offenders = _offenders(ROOT)
    assert not offenders, "; ".join(offenders)


def _plant(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!" + "/Us" + "ers/someone/proj/bin/python3\n", encoding="utf-8")


def test_gate_walk_skips_virtual_environments_but_not_sources(tmp_path):
    for rel in (".venv/lib/a.py", "venv/bin/pip", ".tox/py39/x.py", "pkg.egg-info/PKG-INFO"):
        _plant(tmp_path, rel)
    assert _offenders(tmp_path) == []
    _plant(tmp_path, "src/b.py")
    assert _offenders(tmp_path) == ["src/b.py: contains a home directory path"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_gate_in_a_git_checkout_scans_tracked_files_only(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    _plant(tmp_path, ".venv/lib/a.py")
    _plant(tmp_path, "notes/untracked.txt")
    assert _offenders(tmp_path) == []
    _plant(tmp_path, "src/tracked.py")
    subprocess.run(["git", "-C", str(tmp_path), "add", "src/tracked.py"], check=True, capture_output=True)
    assert _offenders(tmp_path) == ["src/tracked.py: contains a home directory path"]


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
