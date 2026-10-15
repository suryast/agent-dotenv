from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import agent_dotenv
from agent_dotenv.adapters import claude_code
from agent_dotenv.adapters_api import BuildContext
from agent_dotenv.adapters.claude_code_loader import session_start
from agent_dotenv.frontmatter import parse
from agent_dotenv.layers import load_layer
from agent_dotenv.pipeline import BuildResult, run_build
from tests.conftest import FIXTURE_SOURCE, make_source

LAYERS_VAR = "AGENT_DOTENV_LAYERS"
NAME = "claude-code"
MARKERS = (b"EXT_MARKER_91bc", b"SENS_MARKER_7f3a", b"PATHS_ENV_MARKER_55")
CLEAN_PATH = "/usr/bin:/bin"
FAILURE_LINE = "agent-dotenv: context loader failed (RuntimeError); continuing without it"


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


def fake_token() -> str:
    # Built at runtime so no token-shaped literal lives in the repo.
    return "gh" + "p_" + "Q7" * 18


def all_text(result: BuildResult) -> str:
    return "\n".join(result.errors + result.warnings + [repr(f) for f in result.findings])


def source_with_paths_env(tmp_path: Path) -> Path:
    source = make_source(tmp_path)
    (source / "local" / "paths.env").write_text(
        "VAULT_PATH=/vault\nSECRET_NOTE=PATHS_ENV_MARKER_55\n", encoding="utf-8"
    )
    return source


def external_env(source: Path) -> dict:
    return {LAYERS_VAR: str(source / "external_acme")}


def build_plugin(source: Path, env: dict) -> Path:
    result = run_build(source, [NAME], env=env)
    assert result.ok, result.errors
    return source / "dist" / NAME


def plugin_files(plugin: Path) -> dict:
    return {
        p.relative_to(plugin).as_posix(): p.read_bytes()
        for p in sorted(plugin.rglob("*"))
        if p.is_file()
    }


def hook_command(plugin: Path, args=(), flags=()) -> list:
    return [sys.executable] + list(flags) + [str(plugin / "loader" / "session_start.py")] + list(args)


def run_hook(
    plugin: Path, cwd: Path, env: dict, *args: str, flags=()
) -> subprocess.CompletedProcess:
    cwd.mkdir(parents=True, exist_ok=True)
    full_env = {"PATH": CLEAN_PATH}
    full_env.update(env)
    return subprocess.run(
        hook_command(plugin, args, flags),
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )


def hook_context(proc: subprocess.CompletedProcess) -> str:
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload) == {"hookSpecificOutput"}
    inner = payload["hookSpecificOutput"]
    assert set(inner) == {"hookEventName", "additionalContext"}
    assert inner["hookEventName"] == "SessionStart"
    return inner["additionalContext"]


# --- adapter output ---------------------------------------------------------


def test_plugin_layout(tmp_path):
    source = source_with_paths_env(tmp_path)
    plugin = build_plugin(source, external_env(source))
    files = plugin_files(plugin)
    assert set(files) == {
        ".claude-plugin/plugin.json",
        "hooks/hooks.json",
        "skills/demo/SKILL.md",
        "loader/frontmatter.py",
        "loader/layers.py",
        "loader/session_start.py",
        "loader/home.txt",
        "loader/base/rules.md",
        "loader/base/identity.md",
    }
    manifest = json.loads(files[".claude-plugin/plugin.json"])
    assert manifest["name"] == "agent-dotenv"
    assert manifest["version"] == agent_dotenv.__version__
    assert files["loader/home.txt"].decode() == str(source.resolve())
    package = Path(agent_dotenv.__file__).parent
    assert files["loader/frontmatter.py"] == (package / "frontmatter.py").read_bytes()
    assert files["loader/layers.py"] == (package / "layers.py").read_bytes()
    assert files["loader/session_start.py"] == Path(session_start.__file__).read_bytes()
    meta, body = parse(files["loader/base/rules.md"].decode())
    assert (meta.scope, meta.targets, body) == ("personal", None, "FIXTURE_RULE: be brief.\n")
    assert files["skills/demo/SKILL.md"] == (
        FIXTURE_SOURCE / "base" / "skills" / "demo" / "SKILL.md"
    ).read_bytes()


def test_no_external_or_sensitive_marker_anywhere_in_plugin(tmp_path):
    source = source_with_paths_env(tmp_path)
    plugin = build_plugin(source, external_env(source))
    files = plugin_files(plugin)
    assert files
    forbidden = MARKERS + (b"glossary", b"Acme terms", b"Alice", b"people/a.md")
    for rel, data in files.items():
        for marker in forbidden:
            assert marker not in data, "%r found in %s" % (marker, rel)
            assert marker not in rel.encode(), "%r found in path %s" % (marker, rel)
    for path in plugin.rglob("*"):
        for marker in forbidden:
            assert marker not in path.name.encode()
    assert not (plugin / "loader" / "base" / "notes.md").exists()


@pytest.mark.parametrize("scope", ["external", "sensitive"])
def test_external_scope_base_file_not_bundled(tmp_path, scope):
    source = make_source(tmp_path)
    write_md(source / "base" / "vendor.md", "---\nscope: %s\n---\nVENDOR_MARKER_3c\n" % scope)
    plugin = build_plugin(source, external_env(source))
    assert not (plugin / "loader" / "base" / "vendor.md").exists()
    for rel, data in plugin_files(plugin).items():
        assert b"VENDOR_MARKER_3c" not in data, rel


def test_base_text_kept_under_local_append(tmp_path):
    source = make_source(tmp_path)
    write_md(
        source / "local" / "identity.md",
        "---\nscope: personal\nmode: append\n---\nLOCAL_HALF\n",
    )
    plugin = build_plugin(source, {})
    meta, body = parse((plugin / "loader" / "base" / "identity.md").read_text(encoding="utf-8"))
    assert (meta.scope, body) == ("personal", "FIXTURE_IDENTITY: uses a terminal.\n")
    proc = run_hook(plugin, tmp_path / "elsewhere", {}, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == (
        "FIXTURE_RULE: be brief.\n\nFIXTURE_IDENTITY: uses a terminal.\n\nLOCAL_HALF\n"
    )


def test_external_override_keeps_base_rules_bundled(tmp_path):
    source = make_source(tmp_path)
    write_md(
        source / "external_acme" / "rules.md",
        "---\nscope: personal\n---\nEXT_RULE_MARKER_4d\n",
    )
    plugin = build_plugin(source, external_env(source))
    meta, body = parse((plugin / "loader" / "base" / "rules.md").read_text(encoding="utf-8"))
    assert body == "FIXTURE_RULE: be brief.\n"
    for rel, data in plugin_files(plugin).items():
        assert b"EXT_RULE_MARKER_4d" not in data, rel


def test_stale_output_removed(tmp_path):
    source = make_source(tmp_path)
    extra = source / "base" / "extra.md"
    write_md(extra, "---\nscope: personal\n---\nSTALE_MARKER_42\n")
    plugin = build_plugin(source, {})
    assert (plugin / "loader" / "base" / "extra.md").is_file()
    write_md(extra, "---\nscope: sensitive\n---\nSTALE_MARKER_42\n")
    plugin = build_plugin(source, {})
    assert not (plugin / "loader" / "base" / "extra.md").exists()
    for rel, data in plugin_files(plugin).items():
        assert b"STALE_MARKER_42" not in data, rel


def test_hooks_json_command_and_wrapper(tmp_path):
    plugin = build_plugin(make_source(tmp_path), {})
    hooks = json.loads((plugin / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    assert hooks == {
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": 'python3 "${CLAUDE_PLUGIN_ROOT}/loader/session_start.py"',
                        }
                    ]
                }
            ]
        }
    }


def test_paths_env_not_emitted(tmp_path):
    source = source_with_paths_env(tmp_path)
    plugin = build_plugin(source, external_env(source))
    assert not list(plugin.rglob("paths.env*"))
    for rel, data in plugin_files(plugin).items():
        assert b"PATHS_ENV_MARKER_55" not in data, rel
        assert b"VAULT_PATH=" not in data, rel


def test_local_skill_replaces_base_skill(tmp_path):
    source = make_source(tmp_path)
    (source / "local" / "skills" / "demo").mkdir(parents=True)
    (source / "local" / "skills" / "demo" / "SKILL.md").write_text("local demo\n", encoding="utf-8")
    plugin = build_plugin(source, {})
    assert (plugin / "skills" / "demo" / "SKILL.md").read_text(encoding="utf-8") == "local demo\n"


# --- build-time scan of the session context ---------------------------------


def test_session_context_is_scanned(tmp_path):
    source = make_source(tmp_path)
    token = fake_token()
    write_md(
        source / "external_acme" / "leak.md",
        """
        ---
        scope: external
        description: key %s
        ---
        body
        """ % token,
    )
    result = run_build(source, [NAME], env=external_env(source))
    assert not result.ok
    assert [(f.file, f.kind) for f in result.findings] == [
        ("claude-code/session-context", "pattern:ghp")
    ]
    assert token not in all_text(result)
    assert not (source / "dist").exists()


def test_local_value_in_context_matching_secret_ref_fails(tmp_path):
    source = make_source(tmp_path)
    value = "s3cr3t-" + "vault-for-tests"
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    result = run_build(source, [NAME], env={"MY_SECRET": value, "VAULT_PATH": value})
    assert not result.ok
    assert [(f.file, f.kind) for f in result.findings] == [
        ("claude-code/session-context", "secret-ref:MY_SECRET")
    ]
    assert value not in all_text(result)
    assert not (source / "dist").exists()


# --- the bundled hook, run as a script --------------------------------------


def test_bundled_hook_runs_as_script_from_unrelated_cwd(tmp_path):
    source = source_with_paths_env(tmp_path)
    plugin = build_plugin(source, {})
    layer = source / "external_acme"
    proc = run_hook(plugin, tmp_path / "elsewhere", {LAYERS_VAR: str(layer)})
    context = hook_context(proc)
    assert proc.stderr == ""
    lines = context.splitlines()
    assert "FIXTURE_RULE: be brief." in context
    assert "FIXTURE_IDENTITY: uses a terminal." in context
    assert "%s/glossary.md: Acme terms" % layer in lines
    assert "%s/people/a.md: Alice" % layer in lines
    assert "VAULT_PATH=/vault" in lines
    assert "EXT_MARKER_91bc" not in context
    assert "Alice works" not in context
    assert "SENS_MARKER_7f3a" not in context
    assert "PATHS_ENV_MARKER_55" not in context
    assert lines[-1] == "VAULT_PATH=/vault"  # an unset or valid layer list gives no warning


def test_hook_plain_format_and_no_layers(tmp_path):
    plugin = build_plugin(make_source(tmp_path), {})
    proc = run_hook(plugin, tmp_path / "elsewhere", {}, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "FIXTURE_RULE: be brief.\n\nFIXTURE_IDENTITY: uses a terminal.\n"


def test_hook_exits_zero_on_missing_layer_malformed_frontmatter_and_non_utf8(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    layer = source / "external_acme"
    (layer / "bad.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (layer / "bin.md").write_bytes(b"---\nscope: external\ndescription: BIN\n---\n\xff\xfe\n")
    (source / "local" / "broken.md").write_text("---\nscope: nope\n---\nx\n", encoding="utf-8")
    (source / "local" / "rules.md").write_bytes(b"---\nscope: personal\n---\n\xff\xfe\n")
    missing = tmp_path / "missing-layer"
    proc = run_hook(plugin, tmp_path / "elsewhere", {LAYERS_VAR: "%s:%s" % (missing, layer)})
    context = hook_context(proc)
    assert proc.stderr == ""
    lines = context.splitlines()
    assert "FIXTURE_RULE: be brief." in context  # the unreadable local override is skipped
    assert "%s/glossary.md: Acme terms" % layer in lines
    assert "bad.md" not in context
    assert "BIN" not in context
    assert str(missing) in lines[-1]


def test_hook_warnings_are_last_lines(tmp_path):
    plugin = build_plugin(make_source(tmp_path), {})
    env = {LAYERS_VAR: "relative/path::%s" % (tmp_path / "missing")}
    proc = run_hook(plugin, tmp_path / "elsewhere", env, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert "relative/path" in lines[-3]
    assert "empty entry" in lines[-2]
    assert str(tmp_path / "missing") in lines[-1]
    assert lines[0] == "FIXTURE_RULE: be brief."


def test_hook_exits_zero_on_unexpected_exception(tmp_path, capsys, monkeypatch):
    plugin = build_plugin(make_source(tmp_path), {})

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(session_start, "load_layer", boom)
    rc = session_start.main([], {}, root=plugin / "loader")
    out, err = capsys.readouterr()
    assert rc == 0
    assert err == ""
    payload = json.loads(out)
    assert payload["hookSpecificOutput"]["additionalContext"] == FAILURE_LINE
    assert "kaboom" not in out


@pytest.mark.parametrize("error", ["RuntimeError('broken')", "SystemExit(3)"])
def test_hook_exits_zero_when_a_bundled_module_fails_to_import(tmp_path, error):
    plugin = build_plugin(make_source(tmp_path), {})
    (plugin / "loader" / "layers.py").write_text("raise %s\n" % error, encoding="utf-8")
    context = hook_context(run_hook(plugin, tmp_path / "elsewhere", {}))
    kind = error.split("(")[0]
    assert context == FAILURE_LINE.replace("RuntimeError", kind)


@pytest.mark.parametrize("fmt", [(), ("--format", "plain")])
def test_hook_exits_zero_when_stdout_is_closed(tmp_path, fmt):
    plugin = build_plugin(make_source(tmp_path), {})
    read_end, write_end = os.pipe()
    os.close(read_end)  # nobody reads: every write gives EPIPE
    try:
        proc = subprocess.run(
            hook_command(plugin, fmt),
            cwd=str(tmp_path),
            env={"PATH": CLEAN_PATH},
            stdout=write_end,
            stderr=subprocess.PIPE,
            text=True,
        )
    finally:
        os.close(write_end)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


def test_hook_runs_in_isolated_mode(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    env = {LAYERS_VAR: str(source / "external_acme")}
    context = hook_context(run_hook(plugin, tmp_path / "elsewhere", env, flags=("-I",)))
    assert context.startswith("FIXTURE_RULE: be brief.")
    assert "glossary.md: Acme terms" in context


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="PYTHONSAFEPATH exists only in Python 3.11 and later"
)
def test_hook_runs_with_pythonsafepath(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    env = {"PYTHONSAFEPATH": "1", LAYERS_VAR: str(source / "external_acme")}
    context = hook_context(run_hook(plugin, tmp_path / "elsewhere", env))
    assert context.startswith("FIXTURE_RULE: be brief.")
    assert "glossary.md: Acme terms" in context


def test_hook_survives_decoy_frontmatter_module_in_cwd_and_pythonpath(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    decoy_cwd = tmp_path / "decoy_cwd"
    decoy_pp = tmp_path / "decoy_pp"
    for folder in (decoy_cwd, decoy_pp):
        folder.mkdir()
        for module in ("frontmatter", "layers", "session_start"):
            (folder / ("%s.py" % module)).write_text(
                "raise RuntimeError('DECOY_%s')\n" % module, encoding="utf-8"
            )
    env = {"PYTHONPATH": str(decoy_pp), LAYERS_VAR: str(source / "external_acme")}
    proc = run_hook(plugin, decoy_cwd, env)
    context = hook_context(proc)
    assert "FIXTURE_RULE: be brief." in context
    assert "glossary.md: Acme terms" in context
    assert "DECOY" not in proc.stdout + proc.stderr


def test_hook_survives_decoy_agent_dotenv_package_in_cwd_and_pythonpath(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    decoy_cwd = tmp_path / "decoy_cwd"
    decoy_pp = tmp_path / "decoy_pp"
    for folder in (decoy_cwd, decoy_pp):
        package = folder / "agent_dotenv"
        package.mkdir(parents=True)
        for module in ("__init__", "layers", "frontmatter"):
            (package / ("%s.py" % module)).write_text(
                "print('DECOY_PKG_%s')\nraise RuntimeError('DECOY_PKG_%s')\n" % (module, module),
                encoding="utf-8",
            )
    env = {"PYTHONPATH": str(decoy_pp), LAYERS_VAR: str(source / "external_acme")}
    proc = run_hook(plugin, decoy_cwd, env)
    assert "DECOY" not in proc.stdout + proc.stderr
    context = hook_context(proc)
    assert "FIXTURE_RULE: be brief." in context
    assert "glossary.md: Acme terms" in context


def test_hook_without_home_txt_skips_local(tmp_path, capsys):
    source = source_with_paths_env(tmp_path)
    plugin = build_plugin(source, {})
    (plugin / "loader" / "home.txt").unlink()
    rc = session_start.main(["--format", "plain"], {}, root=plugin / "loader")
    out = capsys.readouterr().out
    assert rc == 0
    assert "FIXTURE_RULE" in out
    assert "VAULT_PATH" not in out


def test_hook_hides_sensitive_base_text_behind_local_append(tmp_path, capsys):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    loader = plugin / "loader"
    write_md(loader / "base" / "identity.md", "---\nscope: sensitive\n---\nLEAK_MARKER_BASE\n")
    write_md(
        source / "local" / "identity.md",
        "---\nscope: personal\nmode: append\n---\nlocal identity\n",
    )
    rc = session_start.main(["--format", "plain"], {}, root=loader)
    out = capsys.readouterr().out
    assert rc == 0
    assert "LEAK_MARKER_BASE" not in out
    assert "local identity" in out


# --- run-time confidentiality ------------------------------------------------


@pytest.mark.parametrize("mode", ["replace", "append"])
def test_hook_never_prints_external_rules_or_identity_body(tmp_path, mode):
    source = make_source(tmp_path)
    layer = source / "external_acme"
    write_md(layer / "rules.md", "---\nscope: external\nmode: %s\n---\nEXT_RULES_BODY_1\n" % mode)
    write_md(
        layer / "identity.md",
        "---\nscope: personal\nmode: %s\n---\nEXT_IDENTITY_BODY_2\n" % mode,
    )
    plugin = build_plugin(source, {LAYERS_VAR: str(layer)})
    proc = run_hook(plugin, tmp_path / "elsewhere", {LAYERS_VAR: str(layer)}, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "EXT_RULES_BODY_1" not in out
    assert "EXT_IDENTITY_BODY_2" not in out
    assert "FIXTURE_RULE: be brief." in out
    assert "FIXTURE_IDENTITY: uses a terminal." in out
    lines = out.splitlines()
    for key in ("rules.md", "identity.md"):
        assert [line for line in lines if key in line] == [str(layer / key)]


def test_hook_hides_local_external_scope_file_without_external_layer(tmp_path):
    source = make_source(tmp_path)
    plugin = build_plugin(source, {})
    write_md(source / "local" / "rules.md", "---\nscope: external\n---\nLOCAL_EXT_BODY_5\n")
    proc = run_hook(plugin, tmp_path / "elsewhere", {}, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    assert "LOCAL_EXT_BODY_5" not in proc.stdout
    assert proc.stdout.startswith("FIXTURE_RULE: be brief.")


# --- the external index -------------------------------------------------------


def two_layers(tmp_path):
    e1 = tmp_path / "e1"
    e2 = tmp_path / "e2"
    write_md(e1 / "glossary.md", "---\nscope: external\ndescription: Acme terms\n---\nEXT_MARKER_91bc\n")
    write_md(e2 / "glossary.md", "---\nscope: sensitive\ndescription: hidden\n---\nSENS_MARKER_7f3a\n")
    return e1, e2


def build_scan_text(source: Path, roots) -> str:
    ctx = BuildContext(
        sources={},
        skills={},
        external_index={},
        external_roots=tuple(roots),
        local_values={},
        source_dir=source,
        options={},
    )
    return claude_code.build(ctx).scan_texts["session-context"]


def test_index_falls_back_to_earlier_layer_when_later_file_is_dropped(tmp_path):
    source = make_source(tmp_path)
    e1, e2 = two_layers(tmp_path)
    plugin = build_plugin(source, {})
    env = {LAYERS_VAR: "%s:%s" % (e1, e2)}
    proc = run_hook(plugin, tmp_path / "elsewhere", env, "--format", "plain")
    assert proc.returncode == 0, proc.stderr
    for text in (proc.stdout, build_scan_text(source, [e1, e2])):
        assert "%s: Acme terms" % (e1 / "glossary.md") in text.splitlines()
        assert str(e2) not in text
        assert "hidden" not in text


def test_collect_index_returns_paths_of_the_winning_layer(tmp_path):
    e1 = tmp_path / "e1"
    e2 = tmp_path / "e2"
    write_md(e1 / "x.md", "---\nscope: external\ndescription: one\n---\nbody\n")
    write_md(e1 / "only-first.md", "---\nscope: external\n---\nbody\n")
    write_md(e2 / "x.md", "---\nscope: personal\ndescription: two\n---\nbody\n")
    assert session_start.collect_index([e1, e2]) == [
        (str(e1 / "only-first.md"), ""),
        (str(e2 / "x.md"), "two"),
    ]


def test_collect_index_skips_sensitive_and_malformed_files(tmp_path):
    e1 = tmp_path / "e1"
    write_md(e1 / "ok.md", "---\nscope: external\ndescription: fine\n---\nbody\n")
    write_md(e1 / "secret.md", "---\nscope: sensitive\ndescription: nope\n---\nbody\n")
    (e1 / "bad.md").write_text("no frontmatter at all\n", encoding="utf-8")
    (e1 / "bin.md").write_bytes(b"---\nscope: external\n---\n\xff\xfe\n")
    assert session_start.collect_index([e1]) == [(str(e1 / "ok.md"), "fine")]


def test_collect_index_ignores_external_skills_without_warning(tmp_path, recwarn):
    e1 = tmp_path / "e1"
    write_md(e1 / "ok.md", "---\nscope: external\n---\nbody\n")
    write_md(e1 / "skills" / "x" / "SKILL.md", "skill\n")
    assert session_start.collect_index([e1]) == [(str(e1 / "ok.md"), "")]
    assert len(recwarn) == 0


# --- render_context ---------------------------------------------------------


def fixture_base():
    return load_layer(FIXTURE_SOURCE / "base", "base")[0]


def test_render_context_order():
    root = FIXTURE_SOURCE / "external_acme"
    index = [(str(root / "people" / "a.md"), "Alice"), (str(root / "glossary.md"), "Acme terms")]
    text = session_start.render_context(
        fixture_base(),
        index,
        {"DEVICE_NAME": "mac", "VAULT_PATH": "/vault"},
        ["first warning", "second warning"],
    )
    order = [
        text.index("FIXTURE_RULE"),
        text.index("FIXTURE_IDENTITY"),
        text.index("%s/glossary.md: Acme terms" % root),
        text.index("%s/people/a.md: Alice" % root),
        text.index("VAULT_PATH=/vault"),
        text.index("DEVICE_NAME=mac"),
        text.index("first warning"),
    ]
    assert order == sorted(order)
    assert text.splitlines()[-2:] == ["first warning", "second warning"]
    assert "SENS_MARKER_7f3a" not in text  # notes.md is not rules or identity


def test_render_context_path_only_without_description():
    text = session_start.render_context({}, [("/co/people/a.md", "")], {}, [])
    assert text == "/co/people/a.md"


def test_adapter_constants():
    assert claude_code.NAME == "claude-code"
    assert claude_code.ACCEPTS_EXTERNAL is True
    assert os.path.basename(session_start.__file__) == "session_start.py"
