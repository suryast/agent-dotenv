"""Command line: init, build, doctor. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Mapping, Optional

from .adapters_api import ADAPTERS_DIR, AdapterError, discover
from .layers import LAYERS_VAR, external_layer_dirs, read_paths_env
from .pipeline import ALL, DIST_DIR, run_build
from .scan import read_secrets_ref
from .templates import LAYER_FILES, SOURCE_FILES

HOME_VAR = "AGENT_DOTENV_HOME"
PATHS_ENV = Path("local") / "paths.env"
PATHS_ENV_EXAMPLE = Path("local") / "paths.env.example"
MIN_PYTHON = (3, 9)
DROPIN_NOTICE = "drop-in adapters run as Python with your permissions"


def _resolve_dir(raw: str, cwd: Path) -> Path:
    path = Path(os.path.expanduser(raw))
    return path if path.is_absolute() else cwd / path


def _source_dir(args: argparse.Namespace, env: Mapping[str, str], cwd: Path) -> Path:
    """The source folder: --source, then AGENT_DOTENV_HOME, then the current directory."""
    raw = args.source or env.get(HOME_VAR)
    return _resolve_dir(raw, cwd) if raw else cwd


def _files_under(root: Path, skip_hidden: bool = True) -> List[Path]:
    """Files under `root`.

    With `skip_hidden`, entries whose name starts with a dot are skipped. The layer loader
    also skips hidden folders, so build and doctor agree on what a source is. Build output
    is walked with skip_hidden=False, because an adapter may write only into hidden paths."""
    found: List[Path] = []
    if not root.is_dir():
        return found
    for dirpath, dirs, names in os.walk(str(root)):
        dirs[:] = [d for d in dirs if not (skip_hidden and d.startswith(".")) and d != "__pycache__"]
        found.extend(
            Path(dirpath) / name
            for name in names
            if not (skip_hidden and name.startswith(".")) and (Path(dirpath) / name).is_file()
        )
    return found


def _write_new(path: Path, text: str) -> bool:
    """Create `path` with `text`. Return False and change nothing when it already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(str(path), "x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        return False
    return True


def _set_paths_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    new = "%s=%s" % (key, value)
    for i, line in enumerate(lines):
        if line.split("=", 1)[0].strip() == key:
            lines[i] = new
            break
    else:
        lines.append(new)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def cmd_init(args: argparse.Namespace, env: Mapping[str, str], cwd: Path) -> int:
    source = _resolve_dir(args.source, cwd) if args.source else cwd
    layer: Optional[Path] = None
    if args.layer:
        expanded = os.path.expanduser(args.layer)
        if not os.path.isabs(expanded):
            print("error: --layer must be an absolute path, got %r" % args.layer)
            return 1
        layer = Path(os.path.abspath(expanded))  # removes ".." so the checks see the real folder
        if layer.exists() and (not layer.is_dir() or any(layer.iterdir())):
            print("error: %s is not empty; refusing to write the layer template into it" % layer)
            return 1

    for rel, text in SOURCE_FILES.items():
        target = source / rel
        print("%s %s" % ("created" if _write_new(target, text) else "kept   ", target))
    paths_env = source / PATHS_ENV
    example = (source / PATHS_ENV_EXAMPLE).read_text(encoding="utf-8")
    if _write_new(paths_env, example):
        print("created %s" % paths_env)

    if layer is not None:
        for rel, text in LAYER_FILES.items():
            _write_new(layer / rel, text)
        entries = [e for e in read_paths_env(paths_env).get(LAYERS_VAR, "").split(":") if e.strip()]
        known = [os.path.abspath(os.path.expanduser(e)) for e in entries]
        if str(layer) not in known:
            entries.append(str(layer))
        _set_paths_env_value(paths_env, LAYERS_VAR, ":".join(entries))
        print("created layer %s and recorded it in %s" % (layer, paths_env))

    print("next: edit the files in %s" % source)
    print("then run: agent-dotenv build --source %s" % source)
    print("then run: agent-dotenv doctor --source %s" % source)
    return 0


def cmd_build(args: argparse.Namespace, env: Mapping[str, str], cwd: Path) -> int:
    source = _source_dir(args, env, cwd)
    if not source.is_dir():
        print("error: source folder not found: %s" % source)
        return 1
    targets = args.target or [ALL]
    options = {}
    if args.instructions_limit is not None:
        options["instructions_limit"] = str(args.instructions_limit)
    result = run_build(source, targets, env, options)
    for name in sorted(result.written):
        paths = result.written[name]
        print("built %s: %d file(s) in %s" % (name, len(paths), source / DIST_DIR / name))
    for warning in result.warnings:
        print("warning: %s" % warning)
    for error in result.errors:
        print("error: %s" % error)
    for finding in result.findings:
        print("%s:%d %s" % (finding.file, finding.line, finding.kind))
    if not result.ok:
        requested = [t for t in targets if t != ALL]
        try:
            known = sorted(discover(source))
        except AdapterError:
            known = []
        if known and any(t not in known for t in requested):
            print("known targets: %s" % ", ".join([ALL] + known))
    return 0 if result.ok else 1


def _check_secret(name: str, source: str, env: Mapping[str, str]) -> bool:
    """True when the named secret resolves. Output is captured and discarded, never printed."""
    try:
        if source == "env":
            return bool(env.get(name))
        if source.startswith("keychain:"):
            cmd = ["security", "find-generic-password", "-s", source[len("keychain:"):]]
        elif source.startswith("op://"):
            cmd = ["op", "read", source]
        else:
            return False
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def cmd_doctor(args: argparse.Namespace, env: Mapping[str, str], cwd: Path) -> int:
    source = _source_dir(args, env, cwd)
    failures = 0

    def report(ok: bool, text: str) -> None:
        nonlocal failures
        if not ok:
            failures += 1
        print("%s  %s" % ("ok  " if ok else "FAIL", text))

    paths_file = source / PATHS_ENV
    report(paths_file.is_file(), "%s exists" % PATHS_ENV.as_posix())
    paths_env = read_paths_env(paths_file)

    externals: List[Path] = []
    if env.get(LAYERS_VAR) or paths_env.get(LAYERS_VAR):
        externals, layer_warns = external_layer_dirs(env, paths_env)
        for warning in layer_warns:
            report(False, warning)
        for path in externals:
            report(True, "external layer %s" % path)
    else:
        report(True, "%s is not set (no external layers)" % LAYERS_VAR)

    report(
        sys.version_info >= MIN_PYTHON,
        "python %d.%d (need %d.%d or newer)"
        % (sys.version_info[0], sys.version_info[1], MIN_PYTHON[0], MIN_PYTHON[1]),
    )

    try:
        refs = read_secrets_ref(source / "secrets.ref")
    except (ValueError, OSError) as exc:
        report(False, "secrets.ref is invalid: %s" % exc)
        refs = {}
    for name, ref in sorted(refs.items()):
        kind = ref.split(":")[0]
        if _check_secret(name, ref, env):
            report(True, "secret %s resolves (%s)" % (name, kind))
        else:
            report(False, "secret %s does not resolve (%s)" % (name, kind))

    adapter_folder = source / ADAPTERS_DIR
    dropins = sorted(
        p for p in adapter_folder.glob("*.py") if p.is_file() and not p.name.startswith("_")
    ) if adapter_folder.is_dir() else []
    if dropins:
        print(DROPIN_NOTICE)
        for path in dropins:
            report(True, "drop-in adapter %s" % path)
        try:
            discover(source)
        except AdapterError as exc:
            report(False, "adapters do not load: %s" % exc)

    dist_root = source / DIST_DIR
    # Newest file time of each adapter folder. A folder without files has no build output.
    folder_times = {}
    if dist_root.is_dir():
        for folder in sorted(p for p in dist_root.iterdir() if p.is_dir()):
            times = [f.stat().st_mtime for f in _files_under(folder, skip_hidden=False)]
            if times:
                folder_times[folder.name] = max(times)
    if not folder_times:
        where = "" if source == cwd else " --source %s" % source
        report(False, "dist/ has no build output; run: agent-dotenv build%s" % where)
    else:
        source_files = _files_under(source / "base") + _files_under(source / "local")
        source_files.extend(dropins)
        if (source / "secrets.ref").is_file():
            source_files.append(source / "secrets.ref")
        for layer_dir in externals:
            source_files.extend(_files_under(layer_dir))
        newest_source = max((f.stat().st_mtime for f in source_files), default=0.0)
        stale = sorted(name for name, newest in folder_times.items() if newest < newest_source)
        if not stale:
            report(True, "every folder in dist/ is newer than the sources")
        else:
            report(
                False,
                "dist/ is older than the sources in: %s; run build again"
                % ", ".join("dist/%s" % name for name in stale),
            )
    return 1 if failures else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-dotenv",
        description="Build instruction files for several harnesses from one source folder.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init", help="create a source folder and, with --layer, an external layer")
    p_init.add_argument("--source", metavar="DIR", help="source folder (default: current directory)")
    p_init.add_argument("--layer", metavar="DIR", help="create an external layer in this absolute path")
    p_build = sub.add_parser("build", help="build the adapters into dist/")
    p_build.add_argument(
        "--target", action="append", metavar="NAME",
        help="adapter to build; repeat for several (default: all)",
    )
    p_build.add_argument(
        "--source", metavar="DIR",
        help="source folder (default: %s, then the current directory)" % HOME_VAR,
    )
    p_build.add_argument(
        "--instructions-limit", type=int, metavar="N",
        help="character limit that adapters use for their instruction text",
    )
    p_doctor = sub.add_parser("doctor", help="check the environment and the build output")
    p_doctor.add_argument(
        "--source", metavar="DIR",
        help="source folder (default: %s, then the current directory)" % HOME_VAR,
    )
    return parser


def main(
    argv: Optional[List[str]] = None,
    env: Optional[Mapping[str, str]] = None,
    cwd: Optional[Path] = None,
) -> int:
    env = os.environ if env is None else env
    cwd = Path.cwd() if cwd is None else Path(cwd)
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # --help exits 0, a usage error exits 2
        return exc.code if isinstance(exc.code, int) else 1
    handler = {"init": cmd_init, "build": cmd_build, "doctor": cmd_doctor}[args.command]
    return handler(args, env, cwd)
