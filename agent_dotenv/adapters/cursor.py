"""Built-in adapter for Cursor: two always-applied rule files (.mdc)."""
from __future__ import annotations

from ..adapters_api import AdapterOutput, BuildContext

NAME = "cursor"
ACCEPTS_EXTERNAL = False

# (source key, output path, description written into the rule file)
_RULE_FILES = (
    ("rules.md", ".cursor/rules/agent-dotenv-rules.mdc", "Personal working rules"),
    ("identity.md", ".cursor/rules/agent-dotenv-identity.mdc", "Personal identity and context"),
)


def build(ctx: BuildContext) -> AdapterOutput:
    files = {}
    for key, rel, description in _RULE_FILES:
        source = ctx.sources.get(key)
        if source is None:
            continue
        files[rel] = "---\ndescription: %s\nalwaysApply: true\n---\n%s" % (
            description,
            source.body,
        )
    return AdapterOutput(files=files)
