"""Helpers shared by the built-in adapters. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

from typing import List, Mapping

from ..layers import Source

INSTRUCTION_KEYS = ("rules.md", "identity.md")


def render_instructions(sources: Mapping[str, Source]) -> str:
    """Return the body of rules.md, then identity.md, joined by one blank line.

    Each body is stripped. A missing file is skipped. A non-empty result ends
    with one newline. The result is empty when neither file exists."""
    parts: List[str] = []
    for key in INSTRUCTION_KEYS:
        source = sources.get(key)
        if source is None:
            continue
        body = source.body.strip()
        if body:
            parts.append(body)
    if not parts:
        return ""
    return "\n\n".join(parts) + "\n"
