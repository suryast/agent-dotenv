"""The claude-ai-project adapter: instructions text plus external docs, for upload."""
from __future__ import annotations

from typing import Dict, List, Union

from ..adapters_api import AdapterOutput, BuildContext
from ._common import render_instructions

NAME = "claude-ai-project"
# External files are written to docs/ as bodies. The folder is uploaded, not committed.
ACCEPTS_EXTERNAL = True
DEFAULT_LIMIT = 8000
INSTRUCTIONS_FILE = "project-instructions.md"


def build(ctx: BuildContext) -> AdapterOutput:
    warnings: List[str] = []
    raw = ctx.options.get("instructions_limit", str(DEFAULT_LIMIT))
    try:
        limit = int(raw)
    except ValueError:
        limit = DEFAULT_LIMIT
        warnings.append(
            "instructions_limit %r is not an integer, using the default %d" % (raw, DEFAULT_LIMIT)
        )

    # rules.md and identity.md are used whatever their layer.
    text = render_instructions(ctx.sources)
    files: Dict[str, Union[str, bytes]] = {INSTRUCTIONS_FILE: text}
    for key, source in sorted(ctx.external_index.items()):
        files["docs/%s" % key] = source.body

    size = len(text)
    if size > limit:
        warnings.append(
            "%s is %d characters, over the %d character limit" % (INSTRUCTIONS_FILE, size, limit)
        )
    return AdapterOutput(files=files, warnings=warnings)
