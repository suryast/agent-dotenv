"""A drop-in adapter: write the rules as one plain text file."""
from __future__ import annotations

from agent_dotenv.adapters_api import AdapterOutput, BuildContext

NAME = "plain-text"
ACCEPTS_EXTERNAL = False


def build(ctx: BuildContext) -> AdapterOutput:
    rules = ctx.sources.get("rules.md")
    if rules is None:
        return AdapterOutput(files={}, warnings=["rules.md is missing, so nothing was written"])
    return AdapterOutput(files={"notes.txt": rules.body.strip() + "\n"})
