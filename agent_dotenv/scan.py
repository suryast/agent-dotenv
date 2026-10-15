"""Secret scan. Findings carry file, line and kind, never the matched value."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping

MIN_SECRET_LEN = 8  # shorter env values would match ordinary text

PATTERNS = (
    ("ghp", re.compile(r"ghp_[A-Za-z0-9]{36}")),
    ("github_pat", re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("slack", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("aws", re.compile(r"AKIA[0-9A-Z]{16}")),
    # lookbehind: "task-management-..." must not look like an sk- key
    ("sk", re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
)


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    kind: str  # "pattern:<name>" or "secret-ref:<NAME>"; never a value


def read_secrets_ref(path: Path) -> Dict[str, str]:
    """Read NAME=source lines. A missing file gives an empty mapping."""
    refs = {}  # type: Dict[str, str]
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return refs
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        name, sep, source = line.partition("=")
        name, source = name.strip(), source.strip()
        valid = (
            source == "env"
            or (source.startswith("keychain:") and len(source) > len("keychain:"))
            or (source.startswith("op://") and len(source) > len("op://"))
        )
        if not sep or not name or not valid:
            raise ValueError(
                "%s line %d: expected NAME=env, NAME=keychain:<item> or NAME=op://<ref>" % (path, number)
            )
        refs[name] = source
    return refs


def scan(files: Mapping[str, str], secret_names: Iterable[str], env: Mapping[str, str]) -> List[Finding]:
    literals = []
    for name in secret_names:
        value = env.get(name, "").strip()
        if len(value) >= MIN_SECRET_LEN:
            literals.append((name, value))
    findings = []  # type: List[Finding]
    for file, text in files.items():
        for number, line in enumerate(text.splitlines(), start=1):
            for label, pattern in PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(file, number, "pattern:%s" % label))
            for name, value in literals:
                if value in line:
                    findings.append(Finding(file, number, "secret-ref:%s" % name))
    return findings
