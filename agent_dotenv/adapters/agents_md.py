"""The agents-md adapter: one AGENTS.md plus copies of the skill files."""
from __future__ import annotations

from typing import Dict, List, Union

from ..adapters_api import AdapterOutput, BuildContext
from ._common import render_instructions

NAME = "agents-md"
# AGENTS.md is meant to be committed to project repositories, so it never holds external text.
ACCEPTS_EXTERNAL = False


def build(ctx: BuildContext) -> AdapterOutput:
    files: Dict[str, Union[str, bytes]] = {}
    for name, skill in sorted(ctx.skills.items()):
        for rel, data in sorted(skill.files.items()):
            files["skills/%s/%s" % (name, rel)] = data
    text = render_instructions(ctx.sources)
    if ctx.skills:
        lines: List[str] = ["## Skills", ""]
        lines.extend("- skills/%s/SKILL.md" % name for name in sorted(ctx.skills))
        section = "\n".join(lines) + "\n"
        text = text + "\n" + section if text else section
    files["AGENTS.md"] = text
    return AdapterOutput(files=files)
