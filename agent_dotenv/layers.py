"""Layer loading, resolution and filtering. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

import os
import warnings
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Collection, Dict, List, Mapping, Optional, Tuple

try:  # package import (tests, build) or flat import (bundled in a plugin)
    from .frontmatter import FrontmatterError, Meta, parse
except ImportError:  # pragma: no cover - exercised by the bundled plugin
    from frontmatter import FrontmatterError, Meta, parse  # type: ignore

LAYERS_VAR = "AGENT_DOTENV_LAYERS"
SKILLS_DIR = "skills"


@dataclass(frozen=True)
class Source:
    key: str
    meta: Meta
    body: str
    layer: str  # "base", "external" or "local"


@dataclass(frozen=True)
class Skill:
    name: str
    files: Dict[str, bytes]
    layer: str


Layer = Tuple[Dict[str, Source], Dict[str, Skill]]


def _inside(real_root: str, path: Path) -> bool:
    real = os.path.realpath(path)
    return real == real_root or real.startswith(real_root + os.sep)


def _load_source(path: Path, key: str, layer: str, strict: bool) -> Optional[Source]:
    try:
        meta, body = parse(path.read_text(encoding="utf-8"))
    except (FrontmatterError, UnicodeDecodeError, OSError) as exc:
        if strict:
            raise FrontmatterError("%s: %s" % (path, exc)) from exc
        return None
    return Source(key=key, meta=meta, body=body, layer=layer)


def _load_skills(root: Path, real_root: str, layer: str) -> Dict[str, Skill]:
    skills: Dict[str, Skill] = {}
    skills_root = root / SKILLS_DIR
    if not skills_root.is_dir():
        return skills
    for entry in sorted(skills_root.iterdir()):
        if not entry.is_dir() or not _inside(real_root, entry):
            continue
        files: Dict[str, bytes] = {}
        for dirpath, _dirs, names in os.walk(entry):
            for name in names:
                f = Path(dirpath) / name
                if f.is_file() and _inside(real_root, f):
                    files[f.relative_to(entry).as_posix()] = f.read_bytes()
        if files:
            skills[entry.name] = Skill(name=entry.name, files=files, layer=layer)
    return skills


def load_layer(root: Path, layer: str, strict: bool = True) -> Layer:
    root = Path(root)
    sources: Dict[str, Source] = {}
    if not root.is_dir():
        return sources, {}
    real_root = os.path.realpath(root)
    for dirpath, dirs, names in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        if rel_dir == Path("."):
            dirs[:] = [d for d in dirs if d != SKILLS_DIR]
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in sorted(names):
            if not name.endswith(".md"):
                continue
            path = Path(dirpath) / name
            if not path.is_file() or not _inside(real_root, path):
                continue
            key = path.relative_to(root).as_posix()
            source = _load_source(path, key, layer, strict)
            if source is not None:
                sources[key] = source
    if layer == "external":
        if (root / SKILLS_DIR).exists():
            warnings.warn(
                "external layer skills are ignored (%s)" % (root / SKILLS_DIR),
                UserWarning,
            )
        return sources, {}
    return sources, _load_skills(root, real_root, layer)


def resolve(layers: List[Layer]) -> Layer:
    sources: Dict[str, Source] = {}
    skills: Dict[str, Skill] = {}
    for layer_sources, layer_skills in layers:
        for key, src in layer_sources.items():
            earlier = sources.get(key)
            if earlier is not None and src.meta.mode == "append":
                body = earlier.body.rstrip("\n") + "\n\n" + src.body.lstrip("\n")
                src = replace(src, body=body)
            sources[key] = src
        skills.update(layer_skills)
    return sources, skills


def filter_sources(
    sources: Mapping[str, Source], target: str, external_allowed: bool
) -> Dict[str, Source]:
    kept: Dict[str, Source] = {}
    for key, src in sources.items():
        if src.meta.scope == "sensitive":
            continue
        if src.meta.scope == "external" and not external_allowed:
            continue
        if src.meta.targets is not None and target not in src.meta.targets:
            continue
        kept[key] = src
    return kept


def resolve_filtered(
    layers: List[Layer], target: str, external_allowed: bool
) -> Layer:
    """Filter each layer, then resolve.

    Filtering first means a dropped file (sensitive, external without permission,
    wrong target) can never be merged into a later layer's `append` body, and a
    dropped override falls back to the earlier layer."""
    return resolve(
        [
            (filter_sources(sources, target, external_allowed), skills)
            for sources, skills in layers
        ]
    )


def read_paths_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def external_layer_dirs(
    env: Mapping[str, str], paths_env: Mapping[str, str]
) -> Tuple[List[Path], List[str]]:
    """Return the valid external layer directories and one warning per bad entry."""
    raw = env.get(LAYERS_VAR) or paths_env.get(LAYERS_VAR)
    if not raw:
        return [], []
    paths: List[Path] = []
    warns: List[str] = []
    for entry in raw.split(":"):
        entry = entry.strip()
        if not entry:
            warns.append("%s has an empty entry; entry skipped" % LAYERS_VAR)
            continue
        path = Path(os.path.expanduser(entry))
        if not path.is_absolute():
            warns.append(
                "%s entry must be an absolute path, got %r; layer skipped"
                % (LAYERS_VAR, entry)
            )
        elif not path.is_dir():
            warns.append(
                "%s entry is not a directory: %s; layer skipped" % (LAYERS_VAR, path)
            )
        elif path in paths:
            warns.append(
                "%s lists %s more than once; duplicate skipped" % (LAYERS_VAR, path)
            )
        else:
            paths.append(path)
    return paths, warns


def validate_targets(layers: List[Layer], known: Collection[str]) -> None:
    """Raise FrontmatterError when a file names a target that is not in `known`.

    The check is case-sensitive."""
    problems: List[str] = []
    for layer_sources, _skills in layers:
        for key, src in layer_sources.items():
            for name in src.meta.targets or ():
                if name not in known:
                    problems.append(
                        "%s (layer %s): unknown target %r" % (key, src.layer, name)
                    )
    if problems:
        raise FrontmatterError(
            "; ".join(problems) + " (known: %s)" % ", ".join(sorted(known))
        )
