from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

import agent_dotenv.adapters as adapters_pkg
from agent_dotenv.pipeline import BuildResult, run_build
from tests.conftest import make_source

LAYERS_VAR = "AGENT_DOTENV_LAYERS"

# Writes every resolved source body and every skill file, plus a context summary.
DUMP_BODY = """
files = {}
for key, src in ctx.sources.items():
    files["sources/" + key] = src.body
for name, skill in ctx.skills.items():
    for rel, data in skill.files.items():
        files["skills/%s/%s" % (name, rel)] = data
files["context.txt"] = "external_index=%s\\nroots=%d\\n" % (
    sorted(ctx.external_index), len(ctx.external_roots))
return AdapterOutput(files=files)
"""


@pytest.fixture(autouse=True)
def no_builtins(monkeypatch):
    # Later tasks register built-in adapters; these tests use drop-ins only.
    monkeypatch.setattr(adapters_pkg, "BUILTIN", ())


def write_adapter(source: Path, name: str, body: str, accepts: bool = False) -> Path:
    folder = source / "adapters"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("%s.py" % name.replace("-", "_"))
    text = (
        "from agent_dotenv.adapters_api import AdapterOutput\n"
        "NAME = %r\n"
        "ACCEPTS_EXTERNAL = %s\n"
        "\n"
        "def build(ctx):\n" % (name, accepts)
    ) + textwrap.indent(textwrap.dedent(body).strip("\n"), "    ") + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def write_md(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")


def fake_token() -> str:
    # Built at runtime so no token-shaped literal lives in the repo.
    return "gh" + "p_" + "Q7" * 18


def all_text(result: BuildResult) -> str:
    return "\n".join(result.errors + result.warnings + [repr(f) for f in result.findings])


def dist_files(source: Path, name: str) -> dict:
    root = source / "dist" / name
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def tree(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*")}


def plant_earlier_run(source: Path, *names: str) -> None:
    for name in names:
        write_md(source / "dist" / name / "old.txt", "from an earlier run\n")


def test_build_writes_files_under_dist_name(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    result = run_build(source, ["alpha"], env={})
    assert result.ok, result.errors
    assert result.errors == [] and result.findings == []
    root = (source / "dist" / "alpha").absolute()
    assert result.written["alpha"] == sorted(result.written["alpha"])
    assert all(p.is_absolute() and root in p.parents for p in result.written["alpha"])
    assert root / "sources" / "rules.md" in result.written["alpha"]
    files = dist_files(source, "alpha")
    assert set(files) == {p.relative_to(root).as_posix() for p in result.written["alpha"]}
    assert b"FIXTURE_RULE" in files["sources/rules.md"]
    assert files["skills/demo/SKILL.md"].startswith(b"---\nname: demo")
    assert sorted(p.name for p in (source / "dist").iterdir()) == ["alpha"]


def test_unknown_target_fails(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    result = run_build(source, ["nope"], env={})
    assert not result.ok
    assert any("nope" in e and "alpha" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_external_text_only_for_accepting_adapter(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "taker", DUMP_BODY, accepts=True)
    write_adapter(source, "refuser", DUMP_BODY, accepts=False)
    env = {LAYERS_VAR: str(source / "external_acme")}
    result = run_build(source, ["all"], env=env)
    assert result.ok, result.errors
    assert sorted(result.written) == ["refuser", "taker"]
    taker = dist_files(source, "taker")
    refuser = dist_files(source, "refuser")
    assert any(b"EXT_MARKER_91bc" in data for data in taker.values())
    assert "glossary.md" in taker["context.txt"].decode()
    assert "roots=1" in taker["context.txt"].decode()
    assert not any(b"EXT_MARKER_91bc" in data for data in refuser.values())
    assert "external_index=[]" in refuser["context.txt"].decode()


def test_sensitive_marker_never_in_output(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY, accepts=True)
    write_md(
        source / "external_acme" / "secret-notes.md",
        """
        ---
        scope: sensitive
        ---
        SENS_MARKER_7f3a external
        """,
    )
    env = {LAYERS_VAR: str(source / "external_acme")}
    result = run_build(source, ["alpha"], env=env)
    assert result.ok, result.errors
    files = dist_files(source, "alpha")
    assert files
    assert not any(b"SENS_MARKER_7f3a" in data for data in files.values())


def test_filter_before_append_no_leak(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    write_md(
        source / "base" / "identity.md",
        """
        ---
        scope: sensitive
        ---
        SENS_MARKER_7f3a
        """,
    )
    write_md(
        source / "local" / "identity.md",
        """
        ---
        scope: personal
        mode: append
        ---
        LOCAL_APPEND_TEXT
        """,
    )
    result = run_build(source, ["alpha"], env={})
    assert result.ok, result.errors
    identity = dist_files(source, "alpha")["sources/identity.md"]
    assert b"LOCAL_APPEND_TEXT" in identity
    assert b"SENS_MARKER_7f3a" not in identity


def test_stale_output_removed(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    plant_earlier_run(source, "alpha")
    result = run_build(source, ["alpha"], env={})
    assert result.ok, result.errors
    assert not (source / "dist" / "alpha" / "old.txt").exists()
    assert (source / "dist" / "alpha" / "sources" / "rules.md").is_file()


@pytest.mark.parametrize(
    "bad",
    ["../x", "/abs", "{tmp}/abs-outside", "a/../../x", "../../x", "", ".", "a\\b", "a\x00b"],
)
def test_path_traversal_and_absolute_paths_rejected(tmp_path, bad):
    source = make_source(tmp_path)
    bad = bad.replace("{tmp}", str(tmp_path))
    write_adapter(
        source,
        "alpha",
        "return AdapterOutput(files={%r: 'data', 'good.txt': 'ok'})" % bad,
    )
    before = tree(tmp_path)
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("alpha" in e for e in result.errors)
    assert not (source / "dist").exists()
    assert tree(tmp_path) == before


def test_two_paths_that_normalise_to_one_fail(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "return AdapterOutput(files={'a.txt': '1', './a.txt': '2'})")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("alpha" in e and "a.txt" in e for e in result.errors)
    assert not (source / "dist").exists()


@pytest.mark.parametrize(
    "files",
    ["{'a.txt': 3}", "{3: 'x'}", "['a.txt']"],
)
def test_bad_file_content_or_key_fails(tmp_path, files):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "return AdapterOutput(files=%s)" % files)
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("alpha" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_adapter_returning_wrong_type_fails(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "return {'a.txt': 'x'}")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("alpha" in e for e in result.errors)


def test_adapter_exception_deletes_all_output_including_earlier_run(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    write_adapter(source, "zeta", "raise RuntimeError('boom')")
    plant_earlier_run(source, "alpha", "zeta")
    result = run_build(source, ["all"], env={})
    assert not result.ok
    assert any("zeta" in e and "boom" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_failure_keeps_output_of_adapters_not_requested(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "raise RuntimeError('boom')")
    write_adapter(source, "beta", DUMP_BODY)
    plant_earlier_run(source, "alpha", "beta")
    write_md(source / "dist" / "unrelated" / "keep.txt", "keep\n")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert not (source / "dist" / "alpha").exists()
    assert (source / "dist" / "beta" / "old.txt").is_file()
    assert (source / "dist" / "unrelated" / "keep.txt").is_file()


def test_secret_finding_deletes_all_output_and_never_prints_value(tmp_path, capsys):
    source = make_source(tmp_path)
    token = fake_token()
    write_md(
        source / "local" / "leak.md",
        """
        ---
        scope: personal
        targets: [leaky]
        ---
        line one
        token %s here
        """ % token,
    )
    write_adapter(source, "clean", DUMP_BODY)
    write_adapter(source, "leaky", DUMP_BODY)
    plant_earlier_run(source, "clean", "leaky")
    result = run_build(source, ["all"], env={})
    assert not result.ok
    assert [(f.file, f.line, f.kind) for f in result.findings] == [
        ("leaky/sources/leak.md", 2, "pattern:ghp")
    ]
    assert token not in all_text(result)
    assert not (source / "dist").exists()
    out, err = capsys.readouterr()
    assert out == "" and err == ""


def test_scan_texts_are_scanned(tmp_path):
    source = make_source(tmp_path)
    body = (
        "return AdapterOutput(files={'ok.txt': 'fine'}, "
        "scan_texts={'session': 'prefix ' + %r})" % fake_token()
    )
    write_adapter(source, "alpha", body)
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert [(f.file, f.kind) for f in result.findings] == [("alpha/session", "pattern:ghp")]
    assert fake_token() not in all_text(result)
    assert not (source / "dist").exists()


def test_bytes_output_is_scanned_when_utf8(tmp_path):
    source = make_source(tmp_path)
    body = (
        "return AdapterOutput(files={'bin.dat': b'\\xff\\xfe', "
        "'text.bin': ('x ' + %r).encode('utf-8')})" % fake_token()
    )
    write_adapter(source, "alpha", body)
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert [f.file for f in result.findings] == ["alpha/text.bin"]


def test_secret_ref_value_in_output_fails(tmp_path):
    source = make_source(tmp_path)
    value = "s3cr3t-" + "value-for-tests"
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    write_md(
        source / "base" / "creds.md",
        """
        ---
        scope: personal
        ---
        the value is %s
        """ % value,
    )
    write_adapter(source, "alpha", DUMP_BODY)
    result = run_build(source, ["alpha"], env={"MY_SECRET": value})
    assert not result.ok
    assert [(f.file, f.line, f.kind) for f in result.findings] == [
        ("alpha/sources/creds.md", 1, "secret-ref:MY_SECRET")
    ]
    assert value not in all_text(result)
    assert not (source / "dist").exists()


def test_bad_secrets_ref_fails(tmp_path):
    source = make_source(tmp_path)
    (source / "secrets.ref").write_text("MY_SECRET=plain-value\n", encoding="utf-8")
    write_adapter(source, "alpha", DUMP_BODY)
    plant_earlier_run(source, "alpha")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("secrets.ref" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_secret_never_in_error_messages(tmp_path):
    source = make_source(tmp_path)
    value = "s3cr3t-" + "value-for-tests"
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    write_adapter(
        source,
        "alpha",
        "ctx.local_values\nraise RuntimeError('bad ' + %r + ' and ' + %r)" % (fake_token(), value),
    )
    write_adapter(
        source,
        "beta",
        "return AdapterOutput(files={}, warnings=['warn ' + %r])" % fake_token(),
    )
    result = run_build(source, ["all"], env={"MY_SECRET": value})
    assert not result.ok
    text = all_text(result)
    assert "alpha" in text and "beta" in text
    assert fake_token() not in text
    assert value not in text


def test_secret_in_malformed_frontmatter_not_in_error(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    write_md(source / "base" / "oops.md", "---\n%s\n---\nbody\n" % fake_token())
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("oops.md" in e for e in result.errors)
    assert fake_token() not in all_text(result)


def test_secret_ref_value_in_malformed_frontmatter_not_in_error(tmp_path):
    source = make_source(tmp_path)
    value = "s3cr3t-" + "value-for-tests"
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    write_adapter(source, "alpha", DUMP_BODY)
    write_md(source / "base" / "oops.md", "---\n%s\n---\nbody\n" % value)
    result = run_build(source, ["alpha"], env={"MY_SECRET": value})
    assert not result.ok
    assert any("oops.md" in e for e in result.errors)
    assert value not in all_text(result)


def test_malformed_frontmatter_fails_naming_file(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    plant_earlier_run(source, "alpha")
    write_md(source / "base" / "broken.md", "no frontmatter here\n")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("broken.md" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_unknown_frontmatter_target_fails_naming_file(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    write_md(
        source / "local" / "odd.md",
        """
        ---
        scope: personal
        targets: [ghost]
        ---
        body
        """,
    )
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("odd.md" in e and "ghost" in e for e in result.errors)


def test_dropin_load_error_fails(tmp_path):
    source = make_source(tmp_path)
    (source / "adapters").mkdir()
    (source / "adapters" / "broken.py").write_text("def (:\n", encoding="utf-8")
    plant_earlier_run(source, "alpha")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("broken.py" in e for e in result.errors)
    assert not (source / "dist").exists()


def test_missing_external_dir_warns_and_continues(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY, accepts=True)
    missing = tmp_path / "missing-layer"
    result = run_build(source, ["alpha"], env={LAYERS_VAR: str(missing)})
    assert result.ok, result.errors
    assert any(str(missing) in w for w in result.warnings)
    assert "roots=0" in dist_files(source, "alpha")["context.txt"].decode()


def test_external_skills_warning_collected(tmp_path, recwarn):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY, accepts=True)
    write_md(source / "external_acme" / "skills" / "x" / "SKILL.md", "skill\n")
    result = run_build(source, ["alpha"], env={LAYERS_VAR: str(source / "external_acme")})
    assert result.ok, result.errors
    assert any("skills" in w for w in result.warnings)
    assert len(recwarn) == 0


def test_adapter_warnings_prefixed_with_name(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "return AdapterOutput(files={}, warnings=['too long'])")
    result = run_build(source, ["alpha"], env={})
    assert result.ok, result.errors
    assert result.written == {"alpha": []}
    assert any(w.startswith("alpha") and "too long" in w for w in result.warnings)


def test_local_values_from_env_then_paths_env(tmp_path):
    source = make_source(tmp_path)
    (source / "local" / "paths.env").write_text(
        "VAULT_PATH=/from/file\nDEVICE_NAME=file-device\nOTHER=x\n", encoding="utf-8"
    )
    write_adapter(
        source,
        "alpha",
        "return AdapterOutput(files={'v.txt': repr(sorted(ctx.local_values.items()))})",
    )
    result = run_build(source, ["alpha"], env={"VAULT_PATH": "/from/env", "DEVICE_NAME": ""})
    assert result.ok, result.errors
    assert dist_files(source, "alpha")["v.txt"].decode() == repr(
        [("DEVICE_NAME", "file-device"), ("VAULT_PATH", "/from/env")]
    )


def test_options_reach_context(tmp_path):
    source = make_source(tmp_path)
    write_adapter(
        source,
        "alpha",
        "return AdapterOutput(files={'o.txt': repr(sorted(ctx.options.items()))})",
    )
    result = run_build(source, ["alpha"], env={}, options={"instructions_limit": "123"})
    assert result.ok, result.errors
    assert dist_files(source, "alpha")["o.txt"] == b"[('instructions_limit', '123')]"
    result = run_build(source, ["alpha"], env={})
    assert result.ok, result.errors
    assert dist_files(source, "alpha")["o.txt"] == b"[]"


# Fix round 1 (review findings 1 to 6)


def test_failed_discovery_with_all_keeps_user_folders_in_dist(tmp_path):
    source = make_source(tmp_path)
    (source / "adapters").mkdir()
    (source / "adapters" / "broken.py").write_text("def (:\n", encoding="utf-8")
    write_md(source / "dist" / "my-notes" / "keep.md", "mine\n")
    result = run_build(source, ["all"], env={})
    assert not result.ok
    assert (source / "dist" / "my-notes" / "keep.md").is_file()


def test_scan_text_key_cannot_hide_written_file(tmp_path):
    source = make_source(tmp_path)
    body = (
        "return AdapterOutput(files={'session': 'x ' + %r}, "
        "scan_texts={'session': 'clean'})" % fake_token()
    )
    write_adapter(source, "alpha", body)
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert [(f.file, f.kind) for f in result.findings] == [("alpha/session", "pattern:ghp")]
    assert not (source / "dist").exists()


@pytest.mark.parametrize("warns", ["None", "'one string'", "[3]"])
def test_bad_adapter_warnings_fail_and_clean_up(tmp_path, warns):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", "return AdapterOutput(files={'a.txt': 'x'}, warnings=%s)" % warns)
    plant_earlier_run(source, "alpha")
    result = run_build(source, ["alpha"], env={})
    assert not result.ok
    assert any("alpha" in e and "warnings" in e for e in result.errors)
    assert not any(len(w) <= len("alpha: x") for w in result.warnings)
    assert not (source / "dist").exists()


@pytest.mark.parametrize(
    "value",
    [
        "abc\\def-" + "TAILMARK1",
        "it's-a-" + "TAILMARK2",
        "both'and\"-" + "TAILMARK3",
        "tab\there-" + "TAILMARK4",
        "café-key-" + "TAILMARK5",
    ],
)
def test_escaped_secret_value_redacted_in_errors(tmp_path, value):
    source = make_source(tmp_path)
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    write_adapter(source, "alpha", DUMP_BODY)
    write_md(source / "base" / "oops.md", "---\n%s\n---\nbody\n" % value)
    result = run_build(source, ["alpha"], env={"MY_SECRET": value})
    assert not result.ok
    assert any("oops.md" in e for e in result.errors)
    assert "TAILMARK" not in all_text(result)


def test_symlinked_dist_is_refused(tmp_path):
    source = make_source(tmp_path)
    write_adapter(source, "alpha", DUMP_BODY)
    outside = tmp_path / "outside"
    write_md(outside / "alpha" / "old.txt", "not build output\n")
    write_md(outside / "projects" / "p.md", "user data\n")
    (source / "dist").symlink_to(outside, target_is_directory=True)
    before = tree(outside)
    for targets in (["alpha"], ["all"]):
        result = run_build(source, targets, env={})
        assert not result.ok
        assert any("dist" in e and "real directory" in e for e in result.errors)
        assert tree(outside) == before
        assert (source / "dist").is_symlink()


def test_refusing_adapter_gets_no_external_layer_files(tmp_path):
    source = make_source(tmp_path)
    write_md(
        source / "external_acme" / "plain.md",
        """
        ---
        scope: personal
        ---
        EXT_PERSONAL_MARKER
        """,
    )
    body = (
        "return AdapterOutput(files={'keys.txt': repr((sorted(ctx.sources), "
        "sorted(ctx.external_index)))})"
    )
    write_adapter(source, "taker", body, accepts=True)
    write_adapter(source, "refuser", body, accepts=False)
    result = run_build(source, ["all"], env={LAYERS_VAR: str(source / "external_acme")})
    assert result.ok, result.errors
    taker_sources, taker_index = ast.literal_eval(dist_files(source, "taker")["keys.txt"].decode())
    refuser_sources, refuser_index = ast.literal_eval(dist_files(source, "refuser")["keys.txt"].decode())
    assert "plain.md" in taker_sources and "plain.md" in taker_index
    assert "plain.md" not in refuser_sources
    assert refuser_index == []
