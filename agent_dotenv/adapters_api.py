"""Adapter API and discovery. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

import importlib
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Tuple, Union

from .layers import Skill, Source

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ADAPTERS_DIR = "adapters"
BUILTIN_ORIGIN = "builtin"


class AdapterError(Exception):
    """An adapter cannot be loaded or registered."""


@dataclass(frozen=True)
class BuildContext:
    sources: Mapping[str, Source]
    skills: Mapping[str, Skill]
    external_index: Mapping[str, Source]
    external_roots: Tuple[Path, ...]
    local_values: Mapping[str, str]
    source_dir: Path
    options: Mapping[str, str]


@dataclass
class AdapterOutput:
    files: Dict[str, Union[str, bytes]]
    warnings: List[str] = field(default_factory=list)
    scan_texts: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Adapter:
    name: str
    accepts_external: bool
    build: Callable[[BuildContext], AdapterOutput]
    origin: str  # "builtin" or the path of the drop-in file


def _to_adapter(module: object, where: str, origin: str) -> Adapter:
    """Check the three required names of a module. `where` names it in errors."""
    name = getattr(module, "NAME", None)
    if not isinstance(name, str):
        raise AdapterError("%s: missing NAME (a string)" % where)
    if not NAME_PATTERN.fullmatch(name):
        raise AdapterError(
            "%s: bad NAME %r, it must match %s" % (where, name, NAME_PATTERN.pattern)
        )
    accepts = getattr(module, "ACCEPTS_EXTERNAL", None)
    if not isinstance(accepts, bool):
        raise AdapterError("%s: missing ACCEPTS_EXTERNAL (True or False)" % where)
    build = getattr(module, "build", None)
    if not callable(build):
        raise AdapterError("%s: missing callable build" % where)
    return Adapter(name=name, accepts_external=accepts, build=build, origin=origin)


def _load_dropin(path: Path):
    module_name = "agent_dotenv_dropin_%s" % path.stem
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise AdapterError("%s: cannot load this file as a Python module" % path)
    module = importlib.util.module_from_spec(spec)
    # The module must be in sys.modules while it runs (dataclasses need this).
    # Remove it afterwards so drop-ins never leak between calls or tests.
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except (Exception, SystemExit) as exc:
        raise AdapterError("%s: import failed: %s: %s" % (path, type(exc).__name__, exc)) from exc
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


def discover(source_dir: Path) -> Dict[str, Adapter]:
    """Load built-in adapters, then drop-ins from `<source_dir>/adapters/*.py`."""
    found: Dict[str, Adapter] = {}
    origins: Dict[str, str] = {}

    def register(adapter: Adapter, where: str) -> None:
        if adapter.name in found:
            raise AdapterError(
                "%s: adapter name %r is already used by %s"
                % (where, adapter.name, origins[adapter.name])
            )
        found[adapter.name] = adapter
        origins[adapter.name] = where

    builtin_package = importlib.import_module("agent_dotenv.adapters")
    for module in builtin_package.BUILTIN:
        where = getattr(module, "__name__", repr(module))
        register(_to_adapter(module, where, BUILTIN_ORIGIN), where)

    folder = Path(source_dir) / ADAPTERS_DIR
    if folder.is_dir():
        for path in sorted(folder.glob("*.py")):
            if path.name.startswith("_") or not path.is_file():
                continue
            module = _load_dropin(path)
            register(_to_adapter(module, str(path), str(path)), str(path))
    return found
