"""Line-based frontmatter parser. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

SCOPES = ("personal", "external", "sensitive")
MODES = ("replace", "append")
KEYS = ("scope", "mode", "targets", "description")
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")


class FrontmatterError(ValueError):
    pass


@dataclass(frozen=True)
class Meta:
    scope: str
    mode: str = "replace"
    targets: Optional[tuple[str, ...]] = None  # None means all adapters
    description: str = ""


def _parse_targets(value: str) -> tuple[str, ...]:
    if not (value.startswith("[") and value.endswith("]")):
        raise FrontmatterError("targets must look like [a, b]")
    items = tuple(p.strip() for p in value[1:-1].split(","))
    if not items or any(not _NAME_RE.match(item) for item in items):
        raise FrontmatterError(
            "targets must be names like [a, b] matching ^[a-z][a-z0-9-]*$"
        )
    return items


def parse(text: str) -> tuple[Meta, str]:
    if text.startswith("﻿"):
        text = text[1:]
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise FrontmatterError("missing opening --- fence")
    close = next(
        (i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None
    )
    if close is None:
        raise FrontmatterError("missing closing --- fence")
    fields: dict[str, str] = {}
    for i in range(1, close):
        line = lines[i].rstrip("\r\n")
        if not line.strip():
            continue
        key, sep, value = line.partition(":")
        key = key.strip()
        if not sep or key not in KEYS:
            raise FrontmatterError("unknown or malformed key %r" % key)
        fields[key] = value.strip()
    scope = fields.get("scope")
    if scope is None:
        raise FrontmatterError("missing required key: scope")
    if scope not in SCOPES:
        raise FrontmatterError(
            "bad scope %r (use one of %s)" % (scope, ", ".join(SCOPES))
        )
    mode = fields.get("mode", "replace")
    if mode not in MODES:
        raise FrontmatterError("bad mode %r (use one of %s)" % (mode, ", ".join(MODES)))
    targets = _parse_targets(fields["targets"]) if "targets" in fields else None
    meta = Meta(
        scope=scope,
        mode=mode,
        targets=targets,
        description=fields.get("description", ""),
    )
    body = "".join(lines[close + 1 :]).replace("\r\n", "\n")
    return meta, body


def serialize(meta: Meta, body: str) -> str:
    lines = ["---", "scope: %s" % meta.scope, "mode: %s" % meta.mode]
    if meta.targets is not None:
        lines.append("targets: [%s]" % ", ".join(meta.targets))
    if meta.description:
        lines.append("description: %s" % meta.description)
    lines.append("---")
    return "\n".join(lines) + "\n" + body
