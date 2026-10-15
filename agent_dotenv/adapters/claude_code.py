"""claude-code adapter: a Claude Code plugin with skills and a SessionStart hook.

The plugin holds no external layer text. The hook finds the external layers at
session start and prints one index line per external file. At build time the
adapter renders the same session context from `ctx.external_roots` with the
hook's own functions, so the secret scan covers what the hook prints. It reads
only folders named in ctx (`source_dir`, `external_roots`).

Python 3.9 compatible, stdlib only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Union

from .. import __version__, frontmatter, layers
from ..adapters_api import AdapterOutput, BuildContext
from ..frontmatter import serialize
from .claude_code_loader import session_start

NAME = "claude-code"
ACCEPTS_EXTERNAL = True

PLUGIN_NAME = "agent-dotenv"
HOOK_COMMAND = 'python3 "${CLAUDE_PLUGIN_ROOT}/loader/session_start.py"'
SESSION_CONTEXT = "session-context"
LOADER_MODULES = (frontmatter, layers, session_start)


def _json(data: object) -> str:
    return json.dumps(data, indent=2) + "\n"


def build(ctx: BuildContext) -> AdapterOutput:
    files = {}  # type: Dict[str, Union[str, bytes]]
    files[".claude-plugin/plugin.json"] = _json(
        {
            "name": PLUGIN_NAME,
            "version": __version__,
            "description": "Rules, identity and skills from an agent-dotenv source folder",
        }
    )
    files["hooks/hooks.json"] = _json(
        {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": HOOK_COMMAND}]}]}}
    )
    for name, skill in ctx.skills.items():
        for rel, data in skill.files.items():
            files["skills/%s/%s" % (name, rel)] = data
    for module in LOADER_MODULES:
        path = Path(module.__file__)
        files["loader/%s" % path.name] = path.read_text(encoding="utf-8")
    files["loader/home.txt"] = str(Path(ctx.source_dir).resolve())
    # Bundle the filtered base layer itself, not the resolved entries: a later
    # layer's override or `append` must not remove base text from the hook.
    # The build has already loaded this layer strictly. Filtering with
    # external_allowed=False keeps external and sensitive text out.
    base_sources, _ = layers.load_layer(Path(ctx.source_dir) / "base", "base", strict=False)
    for key, source in layers.filter_sources(base_sources, NAME, False).items():
        files["loader/base/%s" % key] = serialize(source.meta, source.body)

    # The index comes from the same function the hook runs, over the roots
    # named in ctx. ctx.external_index is not used.
    context = session_start.render_context(
        {k: s for k, s in ctx.sources.items() if s.layer != "external"},
        session_start.collect_index(ctx.external_roots),
        ctx.local_values,
        [],
    )
    return AdapterOutput(files=files, scan_texts={SESSION_CONTEXT: context})
