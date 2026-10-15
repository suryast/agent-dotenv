"""Claude Code SessionStart hook. Always exits 0; never blocks a session.

The claude-code adapter copies this file flat into the plugin as
loader/session_start.py, beside flat copies of frontmatter.py and layers.py.
Run as a script, the sibling modules are imported flat from the script's
folder. Imported as a package module (tests, build), they come from
agent_dotenv. External layer files are never printed in full: each one
becomes a single `<root>/<key>: <description>` index line.

Python 3.9 compatible, stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings as _warnings
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

_IMPORT_ERROR = None  # type: Optional[BaseException]
try:
    try:
        from agent_dotenv.layers import (
            Source,
            external_layer_dirs,
            load_layer,
            read_paths_env,
            resolve_filtered,
        )
    except ImportError:  # run as a script from the plugin's loader/ folder
        from layers import (  # type: ignore
            Source,
            external_layer_dirs,
            load_layer,
            read_paths_env,
            resolve_filtered,
        )
except Exception as exc:  # a broken bundle must not block the session
    _IMPORT_ERROR = exc

NAME = "claude-code"
TOOL = "agent-dotenv"
CONTEXT_KEYS = ("rules.md", "identity.md")
LOCAL_KEYS = ("VAULT_PATH", "DEVICE_NAME")


def _root_for(key: str, external_roots: Sequence[Path]) -> Path:
    """The last root that holds `key` (later layers win), else the last root."""
    for root in reversed(list(external_roots)):
        if os.path.isfile(os.path.join(str(root), key)):
            return Path(root)
    return Path(list(external_roots)[-1])


def render_context(
    base: Mapping[str, Source],
    external_index: Mapping[str, Source],
    external_roots: Sequence[Path],
    local_values: Mapping[str, str],
    warnings: Sequence[str],
) -> str:
    sections = []  # type: List[str]
    for key in CONTEXT_KEYS:
        source = base.get(key)
        if source is not None and source.body.strip():
            sections.append(source.body.strip())
    if external_index and external_roots:
        lines = []
        for key in sorted(external_index):
            path = "%s/%s" % (str(_root_for(key, external_roots)).rstrip("/"), key)
            description = external_index[key].meta.description
            lines.append("%s: %s" % (path, description) if description else path)
        sections.append("\n".join(lines))
    values = ["%s=%s" % (k, local_values[k]) for k in LOCAL_KEYS if local_values.get(k)]
    if values:
        sections.append("\n".join(values))
    if warnings:
        sections.append("\n".join(warnings))
    return "\n\n".join(sections)


def build_text(env: Mapping[str, str], root: Path) -> str:
    base = load_layer(root / "base", "base", strict=False)
    home_file = root / "home.txt"
    home = None  # type: Optional[Path]
    if home_file.is_file():
        text = home_file.read_text(encoding="utf-8").strip()
        home = Path(text) if text else None
    local = ({}, {})  # type: ignore[var-annotated]
    paths_env = {}  # type: Dict[str, str]
    if home is not None:
        local = load_layer(home / "local", "local", strict=False)
        paths_env = read_paths_env(home / "local" / "paths.env")

    roots, layer_warnings = external_layer_dirs(env, paths_env)
    externals = [load_layer(path, "external", strict=False) for path in roots]
    allowed = bool(roots)
    # Rules and identity come from base and local only. External files give
    # index lines; a key that local overrides is not an external file.
    sources, _ = resolve_filtered([base, local], NAME, allowed)
    everything, _ = resolve_filtered([base] + externals + [local], NAME, allowed)
    index = {k: s for k, s in everything.items() if s.layer == "external"}
    local_values = {}  # type: Dict[str, str]
    for key in LOCAL_KEYS:
        value = env.get(key) or paths_env.get(key)
        if value:
            local_values[key] = value
    return render_context(sources, index, roots, local_values, layer_warnings)


def main(
    argv: Optional[Sequence[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    root: Optional[Path] = None,
) -> int:
    fmt = "json"
    try:
        parser = argparse.ArgumentParser(prog="session_start", add_help=False)
        parser.add_argument("--format", choices=("json", "plain"), default="json")
        args, _unknown = parser.parse_known_args(None if argv is None else list(argv))
        fmt = args.format
    except (Exception, SystemExit):
        fmt = "json"
    try:
        if _IMPORT_ERROR is not None:
            raise _IMPORT_ERROR
        env = os.environ if env is None else env
        root = Path(__file__).resolve().parent if root is None else Path(root)
        with _warnings.catch_warnings():
            _warnings.simplefilter("ignore")
            text = build_text(env, root)
    except Exception as exc:  # the hook must never block a session
        text = "%s: context loader failed (%s); continuing without it" % (
            TOOL,
            type(exc).__name__,
        )
    if fmt == "plain":
        print(text)
    else:
        payload = {
            "hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}
        }
        print(json.dumps(payload))
    return 0


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # last line of defence: exit 0 whatever happens
        pass
    sys.exit(0)
