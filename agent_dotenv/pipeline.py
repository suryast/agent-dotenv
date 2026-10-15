"""Build pipeline: run adapters, scan their output, write it under dist/.

Python 3.9 compatible, stdlib only."""
from __future__ import annotations

import os
import shutil
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .adapters_api import NAME_PATTERN, Adapter, AdapterError, AdapterOutput, BuildContext, discover
from .frontmatter import FrontmatterError
from .layers import (
    Layer,
    external_layer_dirs,
    load_layer,
    read_paths_env,
    resolve_filtered,
    validate_targets,
)
from .scan import MIN_SECRET_LEN, PATTERNS, Finding, read_secrets_ref, scan

ALL = "all"
DIST_DIR = "dist"
LOCAL_KEYS = ("DEVICE_NAME", "VAULT_PATH")
REDACTED = "[redacted]"


@dataclass
class BuildResult:
    ok: bool
    written: dict[str, list[Path]]
    warnings: list[str]
    errors: list[str]
    findings: list[Finding]


# One adapter's checked output: (normalised relative path, bytes) pairs, scan texts.
Checked = Tuple[List[Tuple[str, bytes]], Dict[str, str]]


def _requested(targets: Sequence[str], adapters: Mapping[str, Adapter]) -> Tuple[List[str], List[str]]:
    """Return (adapter names to build, errors)."""
    if not targets:
        return [], ["no target given (use adapter names or %r)" % ALL]
    unknown = [t for t in targets if t != ALL and t not in adapters]
    if unknown:
        return [], [
            "unknown target %r (known: %s)" % (t, ", ".join(sorted(adapters)) or "none")
            for t in unknown
        ]
    if ALL in targets:
        return sorted(adapters), []
    return list(dict.fromkeys(targets)), []


def _cleanup_names(
    targets: Sequence[str], adapters: Optional[Mapping[str, Adapter]], dist: Path
) -> List[str]:
    """Names whose dist/<name>/ a failed run deletes. Only safe names are returned."""
    names = {t for t in targets if t != ALL and NAME_PATTERN.fullmatch(t)}
    if ALL in targets:
        if adapters is not None:
            names.update(adapters)
        elif dist.is_dir():
            names.update(p.name for p in dist.iterdir() if NAME_PATTERN.fullmatch(p.name))
    return sorted(names)


def _remove_outputs(dist: Path, names: Iterable[str]) -> List[str]:
    errors: List[str] = []
    for name in names:
        path = dist / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
        except OSError as exc:
            errors.append("cannot remove %s: %s" % (path, exc))
    return errors


def _check_path(rel: object) -> Optional[str]:
    """Return a reason when `rel` is not a safe path inside dist/<name>/."""
    if not isinstance(rel, str):
        return "path must be a string, got %s" % type(rel).__name__
    if not rel:
        return "empty path"
    if "\\" in rel or "\x00" in rel:
        return "path %r has a backslash or NUL" % rel
    pure = PurePosixPath(rel)
    if pure.is_absolute():
        return "absolute path %r" % rel
    if ".." in pure.parts:
        return "path %r has a '..' component" % rel
    if not pure.parts:
        return "path %r names the output folder itself" % rel
    return None


def _check_output(name: str, output: object) -> Tuple[Optional[Checked], List[str]]:
    if not isinstance(output, AdapterOutput):
        return None, ["adapter %s: build returned %s, not AdapterOutput" % (name, type(output).__name__)]
    if not isinstance(output.files, dict):
        return None, ["adapter %s: files must be a dict" % name]
    if not isinstance(output.scan_texts, dict):
        return None, ["adapter %s: scan_texts must be a dict" % name]
    errors: List[str] = []
    files: List[Tuple[str, bytes]] = []
    seen: Dict[str, object] = {}
    for rel, content in output.files.items():
        reason = _check_path(rel)
        if reason is not None:
            errors.append("adapter %s: %s" % (name, reason))
            continue
        norm = PurePosixPath(rel).as_posix()
        if norm in seen:
            errors.append("adapter %s: paths %r and %r are the same file" % (name, seen[norm], rel))
            continue
        seen[norm] = rel
        if isinstance(content, str):
            try:
                data = content.encode("utf-8")
            except UnicodeEncodeError:
                errors.append("adapter %s: %s is not valid UTF-8 text" % (name, norm))
                continue
        elif isinstance(content, bytes):
            data = content
        else:
            errors.append(
                "adapter %s: %s content must be str or bytes, got %s"
                % (name, norm, type(content).__name__)
            )
            continue
        files.append((norm, data))
    for key, text in output.scan_texts.items():
        if not isinstance(key, str) or not isinstance(text, str):
            errors.append("adapter %s: scan_texts must map str to str" % name)
            break
    if errors:
        return None, errors
    return (files, dict(output.scan_texts)), []


def _redact(text: str, literals: Sequence[str]) -> str:
    for value in literals:
        text = text.replace(value, REDACTED)
    for _label, pattern in PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def _local_values(env: Mapping[str, str], paths_env: Mapping[str, str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for key in LOCAL_KEYS:
        value = env.get(key) or paths_env.get(key)
        if value:
            values[key] = value
    return values


def _load_layers(
    source_dir: Path, externals: Sequence[Path], warns: List[str]
) -> List[Layer]:
    """Load base, each external layer, then local. Raises FrontmatterError or OSError."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        layers = [load_layer(source_dir / "base", "base")]
        layers.extend(load_layer(path, "external") for path in externals)
        layers.append(load_layer(source_dir / "local", "local"))
    warns.extend(str(w.message) for w in caught)
    return layers


def run_build(
    source_dir: Path,
    targets: Sequence[str],
    env: Mapping[str, str],
    options: Optional[Mapping[str, str]] = None,
) -> BuildResult:
    """Build the requested adapters into `source_dir/dist/<name>/`.

    Expected failures do not raise. They return ok=False with messages in
    `errors` and `findings`, and every requested `dist/<name>/` is deleted."""
    source_dir = Path(os.path.abspath(str(source_dir)))
    dist = source_dir / DIST_DIR
    warns: List[str] = []
    errors: List[str] = []
    findings: List[Finding] = []
    secret_names: List[str] = []
    adapters: Optional[Dict[str, Adapter]] = None
    built: Dict[str, Checked] = {}

    def finish(ok: bool, written: Dict[str, List[Path]]) -> BuildResult:
        literals = sorted(
            {v for v in (env.get(n, "").strip() for n in secret_names) if len(v) >= MIN_SECRET_LEN},
            key=len,
            reverse=True,
        )
        if not ok:
            errors.extend(_remove_outputs(dist, _cleanup_names(targets, adapters, dist)))
            try:
                dist.rmdir()  # only succeeds when dist/ is empty
            except OSError:
                pass
            written = {}
        return BuildResult(
            ok=ok,
            written=written,
            warnings=[_redact(w, literals) for w in warns],
            errors=[_redact(e, literals) for e in errors],
            findings=findings,
        )

    # Read secret names first, so every later error message is redacted.
    try:
        secret_names = sorted(read_secrets_ref(source_dir / "secrets.ref"))
    except (ValueError, OSError) as exc:
        errors.append("secrets.ref: %s" % exc)
        return finish(False, {})
    try:
        adapters = discover(source_dir)
    except AdapterError as exc:
        errors.append(str(exc))
        return finish(False, {})
    names, problems = _requested(targets, adapters)
    if problems:
        errors.extend(problems)
        return finish(False, {})

    paths_env = read_paths_env(source_dir / "local" / "paths.env")
    externals, layer_warns = external_layer_dirs(env, paths_env)
    warns.extend(layer_warns)
    try:
        layers = _load_layers(source_dir, externals, warns)
        validate_targets(layers, set(adapters))
    except (FrontmatterError, OSError) as exc:
        errors.append(str(exc))
        return finish(False, {})

    local_values = _local_values(env, paths_env)
    for name in names:
        adapter = adapters[name]
        external_allowed = bool(externals) and adapter.accepts_external
        sources, skills = resolve_filtered(layers, name, external_allowed)
        ctx = BuildContext(
            sources=sources,
            skills=skills,
            external_index={k: s for k, s in sources.items() if s.layer == "external"},
            external_roots=tuple(externals),
            local_values=dict(local_values),
            source_dir=source_dir,
            options=dict(options or {}),
        )
        try:
            output = adapter.build(ctx)
        except (Exception, SystemExit) as exc:
            errors.append("adapter %s: build failed: %s: %s" % (name, type(exc).__name__, exc))
            continue
        checked, problems = _check_output(name, output)
        if checked is None:
            errors.extend(problems)
            continue
        built[name] = checked
        warns.extend("%s: %s" % (name, w) for w in output.warnings)
    if errors:
        return finish(False, {})

    for name in names:
        files, scan_texts = built[name]
        texts: Dict[str, str] = {}
        for rel, data in files:
            try:
                texts["%s/%s" % (name, rel)] = data.decode("utf-8")
            except UnicodeDecodeError:
                pass  # binary output is not scanned
        for key, text in scan_texts.items():
            texts["%s/%s" % (name, key)] = text
        findings.extend(scan(texts, secret_names, env))
    if findings:
        errors.append("secret scan found %d problem(s); no output was kept" % len(findings))
        return finish(False, {})

    errors.extend(_remove_outputs(dist, names))
    if errors:
        return finish(False, {})
    written: Dict[str, List[Path]] = {}
    for name in names:
        root = dist / name
        paths: List[Path] = []
        for rel, data in built[name][0]:
            target = root / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except OSError as exc:
                errors.append("adapter %s: cannot write %s: %s" % (name, rel, exc))
                return finish(False, {})
            paths.append(target)
        written[name] = sorted(paths)
    return finish(True, written)
