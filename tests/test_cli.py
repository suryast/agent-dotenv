from __future__ import annotations

import os
import re
import stat
import sys
import time
from pathlib import Path

import pytest

from agent_dotenv.adapters_api import discover
from agent_dotenv.cli import main
from agent_dotenv.frontmatter import parse
from agent_dotenv.layers import external_layer_dirs, read_paths_env
from agent_dotenv.pipeline import run_build
from agent_dotenv.templates import LAYER_FILES, SOURCE_FILES

from tests.conftest import make_source

TOKEN = "ghp_" + "z" * 36  # built at runtime: no token-shaped literal in this file
SECRET_VALUE = "very-secret-" + "value-1"
DROPIN_LINE = "drop-in adapters run as Python with your permissions"

ECHO_ADAPTER = '''\
from agent_dotenv.adapters_api import AdapterOutput

NAME = "%s"
ACCEPTS_EXTERNAL = False


def build(ctx):
    limit = ctx.options.get("instructions_limit")
    return AdapterOutput(files={"out.txt": "hello\\n"}, warnings=["limit=%%s" %% limit])
'''


def add_dropin(source: Path, name: str = "echo") -> Path:
    folder = source / "adapters"
    folder.mkdir(exist_ok=True)
    path = folder / (name + ".py")
    path.write_text(ECHO_ADAPTER % name, encoding="utf-8")
    return path


HIDDEN_ADAPTER = '''\
from agent_dotenv.adapters_api import AdapterOutput

NAME = "hid"
ACCEPTS_EXTERNAL = False


def build(ctx):
    return AdapterOutput(files={".hidden/x.txt": "hello\\n"})
'''


def add_hidden_dropin(source: Path) -> Path:
    folder = source / "adapters"
    folder.mkdir(exist_ok=True)
    path = folder / "hid.py"
    path.write_text(HIDDEN_ADAPTER, encoding="utf-8")
    return path


def make_ready_source(tmp_path: Path) -> Path:
    """A fixture source with a local/paths.env, as `init` would leave it."""
    source = make_source(tmp_path)
    (source / "local" / "paths.env").write_text(
        (source / "local" / "paths.env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    return source


def files_under(path: Path) -> list:
    return [p for p in path.rglob("*") if p.is_file()] if path.exists() else []


# --- init ---------------------------------------------------------------


def test_init_creates_source_files_and_paths_env(tmp_path, capsys):
    source = tmp_path / "proj"
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    for rel, text in SOURCE_FILES.items():
        assert (source / rel).read_text(encoding="utf-8") == text
    example = (source / "local" / "paths.env.example").read_text(encoding="utf-8")
    assert (source / "local" / "paths.env").read_text(encoding="utf-8") == example
    for rel in ("base/rules.md", "base/identity.md"):
        meta, body = parse(SOURCE_FILES[rel])
        assert meta.scope == "personal"
        assert body.strip()
    out = capsys.readouterr().out
    assert "build" in out
    assert "doctor" in out


def test_init_defaults_to_the_current_directory(tmp_path):
    assert main(["init"], {}, tmp_path) == 0
    assert (tmp_path / "base" / "rules.md").is_file()
    assert (tmp_path / "local" / "paths.env").is_file()


def test_init_never_overwrites(tmp_path):
    source = tmp_path / "proj"
    (source / "base").mkdir(parents=True)
    (source / "local").mkdir()
    (source / "base" / "rules.md").write_text("mine rules", encoding="utf-8")
    (source / "local" / "paths.env").write_text("DEVICE_NAME=mine\n", encoding="utf-8")
    (source / ".gitignore").write_text("mine\n", encoding="utf-8")
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    assert (source / "base" / "rules.md").read_text(encoding="utf-8") == "mine rules"
    assert (source / "local" / "paths.env").read_text(encoding="utf-8") == "DEVICE_NAME=mine\n"
    assert (source / ".gitignore").read_text(encoding="utf-8") == "mine\n"
    assert (source / "base" / "identity.md").is_file()  # the missing files are still created
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0


def test_init_names_missing_gitignore_entries(tmp_path, capsys):
    source = tmp_path / "proj"
    source.mkdir()
    (source / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    assert (source / ".gitignore").read_text(encoding="utf-8") == "node_modules/\n"
    notices = [line for line in capsys.readouterr().out.splitlines() if line.startswith("notice:")]
    assert len(notices) == 1
    assert ".gitignore" in notices[0]
    assert "dist/" in notices[0] and "local/paths.env" in notices[0]

    (source / ".gitignore").write_text("node_modules/\ndist/\n", encoding="utf-8")
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    notices = [line for line in capsys.readouterr().out.splitlines() if line.startswith("notice:")]
    assert len(notices) == 1
    assert "local/paths.env" in notices[0] and "dist/" not in notices[0]


def test_init_is_quiet_about_a_complete_gitignore(tmp_path, capsys):
    source = tmp_path / "proj"
    source.mkdir()
    (source / ".gitignore").write_text("node_modules/\ndist/\nlocal/paths.env\n", encoding="utf-8")
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("notice:")]
    assert main(["init", "--source", str(tmp_path / "fresh")], {}, tmp_path) == 0
    assert not [line for line in capsys.readouterr().out.splitlines() if line.startswith("notice:")]


def test_init_layer_creates_dir_and_records_it(tmp_path, capsys):
    source = tmp_path / "proj"
    layer = tmp_path / "acme"
    assert main(["init", "--source", str(source), "--layer", str(layer)], {}, tmp_path) == 0
    for rel, text in LAYER_FILES.items():
        assert (layer / rel).read_text(encoding="utf-8") == text
    paths_env = source / "local" / "paths.env"
    assert read_paths_env(paths_env)["AGENT_DOTENV_LAYERS"] == str(layer)
    lines = paths_env.read_text(encoding="utf-8").splitlines()
    assert sum(1 for line in lines if line.startswith("AGENT_DOTENV_LAYERS=")) == 1
    dirs, warns = external_layer_dirs({}, read_paths_env(paths_env))
    assert dirs == [layer] and warns == []
    assert str(layer) in capsys.readouterr().out


def test_init_layer_templates_are_external_with_a_description():
    assert set(LAYER_FILES) == {"glossary.md", "repos.md", "tools.md", "people/README.md"}
    for text in LAYER_FILES.values():
        meta, _body = parse(text)
        assert meta.scope == "external"
        assert meta.description


def test_init_layer_appends_with_colon(tmp_path):
    source = tmp_path / "proj"
    (source / "local").mkdir(parents=True)
    (source / "local" / "paths.env").write_text(
        "DEVICE_NAME=mine\nAGENT_DOTENV_LAYERS=/one/layer\n", encoding="utf-8"
    )
    layer = tmp_path / "acme"
    assert main(["init", "--source", str(source), "--layer", str(layer)], {}, tmp_path) == 0
    values = read_paths_env(source / "local" / "paths.env")
    assert values["AGENT_DOTENV_LAYERS"] == "/one/layer:%s" % layer
    assert values["DEVICE_NAME"] == "mine"


def test_init_layer_expands_the_home_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "proj"
    assert main(["init", "--source", str(source), "--layer", "~/acme"], {}, tmp_path) == 0
    assert (tmp_path / "acme" / "glossary.md").is_file()
    assert read_paths_env(source / "local" / "paths.env")["AGENT_DOTENV_LAYERS"] == str(tmp_path / "acme")


def test_init_refuses_nonempty_or_relative_layer(tmp_path, capsys):
    source = tmp_path / "proj"
    nonempty = tmp_path / "taken"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("mine", encoding="utf-8")
    assert main(["init", "--source", str(source), "--layer", str(nonempty)], {}, tmp_path) == 1
    assert "not empty" in capsys.readouterr().out
    assert (nonempty / "keep.txt").read_text(encoding="utf-8") == "mine"
    assert not (nonempty / "glossary.md").exists()

    assert main(["init", "--source", str(source), "--layer", "rel/layer"], {}, tmp_path) == 1
    assert "absolute" in capsys.readouterr().out
    assert not (tmp_path / "rel").exists()

    a_file = tmp_path / "afile"
    a_file.write_text("x", encoding="utf-8")
    assert main(["init", "--source", str(source), "--layer", str(a_file)], {}, tmp_path) == 1
    # a refused layer changes nothing in the source folder
    assert not source.exists()


def test_init_layer_with_dotdot_cannot_overwrite_an_existing_layer(tmp_path, capsys):
    source = tmp_path / "proj"
    layer = tmp_path / "L"
    layer.mkdir()
    (layer / "glossary.md").write_text("my edited glossary", encoding="utf-8")
    sneaky = "%s/nothere/../L" % tmp_path
    assert main(["init", "--source", str(source), "--layer", sneaky], {}, tmp_path) == 1
    assert "not empty" in capsys.readouterr().out
    assert (layer / "glossary.md").read_text(encoding="utf-8") == "my edited glossary"
    assert not (tmp_path / "nothere").exists()


def test_init_layer_records_a_normalised_path_without_duplicates(tmp_path):
    source = tmp_path / "proj"
    (source / "local").mkdir(parents=True)
    layer = tmp_path / "L"
    layer.mkdir()
    (source / "local" / "paths.env").write_text("AGENT_DOTENV_LAYERS=%s\n" % layer, encoding="utf-8")
    sneaky = "%s/x/../L" % tmp_path
    assert main(["init", "--source", str(source), "--layer", sneaky], {}, tmp_path) == 0
    assert read_paths_env(source / "local" / "paths.env")["AGENT_DOTENV_LAYERS"] == str(layer)
    other = tmp_path / "M" / ".." / "N"
    assert main(["init", "--source", str(source), "--layer", str(other)], {}, tmp_path) == 0
    value = read_paths_env(source / "local" / "paths.env")["AGENT_DOTENV_LAYERS"]
    assert value == "%s:%s" % (layer, tmp_path / "N")


def test_init_twice_keeps_every_file(tmp_path):
    source = tmp_path / "proj"
    layer = tmp_path / "acme"
    assert main(["init", "--source", str(source), "--layer", str(layer)], {}, tmp_path) == 0
    edited = [source / "base" / "rules.md", source / "secrets.ref", source / "local" / "paths.env"]
    for path in edited:
        path.write_text(path.read_text(encoding="utf-8") + "# mine\n", encoding="utf-8")
    before = {p: p.read_bytes() for p in files_under(source)}
    assert main(["init", "--source", str(source)], {}, tmp_path) == 0
    assert {p: p.read_bytes() for p in files_under(source)} == before
    assert (layer / "glossary.md").is_file()


# --- build --------------------------------------------------------------


def test_build_all_succeeds_on_fixture(tmp_path, capsys):
    source = make_source(tmp_path)
    names = sorted(discover(source))
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    out = capsys.readouterr().out
    for name in names:
        assert files_under(source / "dist" / name), name
        assert any(name in line for line in out.splitlines()), name


def test_build_source_precedence(tmp_path):
    flag = make_source(tmp_path / "a")
    home = make_source(tmp_path / "b")
    cwd = make_source(tmp_path / "c")
    assert main(["build", "--source", str(flag)], {"AGENT_DOTENV_HOME": str(home)}, cwd) == 0
    assert (flag / "dist").is_dir() and not (home / "dist").exists() and not (cwd / "dist").exists()
    assert main(["build"], {"AGENT_DOTENV_HOME": str(home)}, cwd) == 0
    assert (home / "dist").is_dir() and not (cwd / "dist").exists()
    assert main(["build"], {}, cwd) == 0
    assert (cwd / "dist").is_dir()


def test_build_fails_when_source_folder_is_missing(tmp_path, capsys):
    assert main(["build", "--source", str(tmp_path / "nope")], {}, tmp_path) == 1
    assert "error:" in capsys.readouterr().out


NO_BASE_HINT = "has no base/ folder; run agent-dotenv init or pass --source"


def test_build_fails_without_a_base_folder(tmp_path, capsys):
    source = tmp_path / "proj"
    source.mkdir()
    (source / "unrelated.txt").write_text("x\n", encoding="utf-8")
    assert main(["build", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert "error: %s %s" % (source, NO_BASE_HINT) in out
    assert "built" not in out
    assert not (source / "dist").exists()


def test_doctor_fails_without_a_base_folder(tmp_path, capsys):
    source = tmp_path / "proj"
    source.mkdir()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("FAIL") and NO_BASE_HINT in line for line in out.splitlines())


def test_hidden_skill_file_reaches_no_output(tmp_path):
    source = make_source(tmp_path)
    (source / "base" / "skills" / "demo" / ".DS_Store").write_bytes(b"\x00\x01")
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    assert files_under(source / "dist" / "agents-md" / "skills" / "demo")
    assert not [p for p in files_under(source / "dist") if p.name == ".DS_Store"]


def test_build_single_and_repeated_target(tmp_path):
    source = make_source(tmp_path)
    names = sorted(discover(source))
    assert len(names) >= 3
    assert main(["build", "--source", str(source), "--target", names[0]], {}, tmp_path) == 0
    assert sorted(p.name for p in (source / "dist").iterdir()) == [names[0]]
    args = ["build", "--source", str(source), "--target", names[1], "--target", names[2]]
    assert main(args, {}, tmp_path) == 0
    assert sorted(p.name for p in (source / "dist").iterdir()) == [names[0], names[1], names[2]]


def test_build_unknown_target_fails_listing_names(tmp_path, capsys):
    source = make_source(tmp_path)
    assert main(["build", "--source", str(source), "--target", "nope"], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert "error:" in out and "nope" in out
    for name in discover(source):
        assert name in out
    assert not (source / "dist").exists()


def test_build_failure_removes_output(tmp_path, capsys):
    source = make_source(tmp_path)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    assert files_under(source / "dist")
    (source / "base" / "bad.md").write_text("no frontmatter\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["build", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert "error:" in out and "bad.md" in out
    assert files_under(source / "dist") == []


def test_build_prints_findings_without_values(tmp_path, capsys):
    source = make_source(tmp_path)
    (source / "base" / "rules.md").write_text(
        "---\nscope: personal\n---\nrule\nkey: %s\n" % TOKEN, encoding="utf-8"
    )
    (source / "secrets.ref").write_text("MY_SECRET=env\n", encoding="utf-8")
    (source / "base" / "identity.md").write_text(
        "---\nscope: personal\n---\nuse %s here\n" % SECRET_VALUE, encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {"MY_SECRET": SECRET_VALUE}, tmp_path) == 1
    out = capsys.readouterr().out
    assert re.search(r"^\S+:\d+ pattern:ghp$", out, re.MULTILINE)
    assert re.search(r"^\S+:\d+ secret-ref:MY_SECRET$", out, re.MULTILINE)
    assert "error:" in out
    assert TOKEN not in out
    assert SECRET_VALUE not in out
    assert files_under(source / "dist") == []


def test_build_typo_target_keeps_earlier_output(tmp_path, capsys):
    source = make_source(tmp_path)
    good = ["build", "--source", str(source), "--target", "agents-md", "--target", "cursor"]
    assert main(good, {}, tmp_path) == 0
    capsys.readouterr()
    typo = ["build", "--source", str(source), "--target", "agents-md", "--target", "cusror"]
    assert main(typo, {}, tmp_path) == 1
    assert "cusror" in capsys.readouterr().out
    assert (source / "dist" / "agents-md" / "AGENTS.md").is_file()
    assert files_under(source / "dist" / "cursor")


LEAK_ADAPTER = '''\
from agent_dotenv.adapters_api import AdapterOutput

NAME = "leak"
ACCEPTS_EXTERNAL = False


def build(ctx):
    return AdapterOutput(files={"dir-" + %r + "/x.txt": "x " + %r})
'''


def test_build_redacts_secret_in_finding_path(tmp_path, capsys):
    source = make_source(tmp_path)
    (source / "adapters").mkdir()
    (source / "adapters" / "leak.py").write_text(LEAK_ADAPTER % (SECRET_VALUE, TOKEN), encoding="utf-8")
    (source / "secrets.ref").write_text("MY_TOKEN=env\n", encoding="utf-8")
    env = {"MY_TOKEN": SECRET_VALUE}
    result = run_build(source, ["leak"], env)
    assert [f.file for f in result.findings] == ["leak/dir-[redacted]/x.txt"]
    capsys.readouterr()
    assert main(["build", "--source", str(source), "--target", "leak"], env, tmp_path) == 1
    out = capsys.readouterr().out
    assert "leak/dir-[redacted]/x.txt:1 pattern:ghp" in out
    assert SECRET_VALUE not in out
    assert TOKEN not in out


def test_build_prints_adapter_lines_then_warnings(tmp_path, capsys):
    source = make_source(tmp_path)
    add_dropin(source)
    assert main(["build", "--source", str(source), "--target", "echo"], {}, tmp_path) == 0
    lines = capsys.readouterr().out.splitlines()
    written = [i for i, line in enumerate(lines) if "echo" in line and "warning:" not in line]
    warned = [i for i, line in enumerate(lines) if line.startswith("warning: ")]
    assert len(written) == 1 and len(warned) == 1
    assert written[0] < warned[0]


def test_build_instructions_limit_reaches_the_adapters(tmp_path, capsys):
    source = make_source(tmp_path)
    add_dropin(source)
    assert main(["build", "--source", str(source), "--target", "echo"], {}, tmp_path) == 0
    assert "warning: echo: limit=None" in capsys.readouterr().out
    args = ["build", "--source", str(source), "--target", "echo", "--instructions-limit", "7"]
    assert main(args, {}, tmp_path) == 0
    assert "warning: echo: limit=7" in capsys.readouterr().out


def test_build_warns_about_a_bad_layer_entry(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    (source / "local" / "paths.env").write_text(
        "AGENT_DOTENV_LAYERS=%s\n" % (tmp_path / "missing"), encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    assert "warning: " in capsys.readouterr().out


# --- doctor -------------------------------------------------------------


def test_doctor_fails_without_paths_env(tmp_path, capsys):
    source = make_source(tmp_path)
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert any("FAIL" in line and "paths.env" in line for line in out.splitlines())


def test_doctor_passes_after_build(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    assert "FAIL" not in capsys.readouterr().out


def test_doctor_unset_layers_is_not_a_failure(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    out = capsys.readouterr().out
    assert "AGENT_DOTENV_LAYERS" in out
    assert "FAIL" not in out


def test_doctor_checks_each_layer_path(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    good = source / "external_acme"
    bad = tmp_path / "missing"
    (source / "local" / "paths.env").write_text(
        "AGENT_DOTENV_LAYERS=%s:%s\n" % (good, bad), encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("FAIL") and str(bad) in line for line in out.splitlines())
    assert any(line.startswith("ok") and str(good) in line for line in out.splitlines())


def test_doctor_fails_when_dist_stale(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    newest = max(p.stat().st_mtime for p in files_under(source / "dist"))
    os.utime(source / "base" / "rules.md", (newest + 100, newest + 100))
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("FAIL") and "dist" in line for line in out.splitlines())


def test_doctor_fails_when_an_external_layer_file_is_newer(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    layer = source / "external_acme"
    (source / "local" / "paths.env").write_text(
        "AGENT_DOTENV_LAYERS=%s\n" % layer, encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    newest = max(p.stat().st_mtime for p in files_under(source / "dist"))
    os.utime(layer / "glossary.md", (newest + 100, newest + 100))
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    assert "dist" in capsys.readouterr().out


def test_doctor_ignores_hidden_files_and_folders(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    layer = source / "external_acme"
    (source / "local" / "paths.env").write_text(
        "AGENT_DOTENV_LAYERS=%s\n" % layer, encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    newest = max(p.stat().st_mtime for p in files_under(source / "dist"))
    (layer / ".git").mkdir()
    for hidden in (layer / ".git" / "FETCH_HEAD", source / "base" / ".DS_Store"):
        hidden.write_text("x", encoding="utf-8")
        os.utime(hidden, (newest + 100, newest + 100))
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    assert "FAIL" not in capsys.readouterr().out
    os.utime(source / "base" / "rules.md", (newest + 100, newest + 100))
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1


def test_doctor_fails_after_a_partial_rebuild_and_names_the_stale_folder(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    names = sorted(discover(source))
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    now = time.time()
    for path in files_under(source / "dist"):
        os.utime(path, (now - 100, now - 100))
    os.utime(source / "base" / "rules.md", (now - 50, now - 50))
    assert main(["build", "--source", str(source), "--target", names[0]], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    fails = [line for line in capsys.readouterr().out.splitlines() if line.startswith("FAIL")]
    assert any("dist/%s" % names[1] in line for line in fails)
    assert not any("dist/%s" % names[0] in line for line in fails)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0


def test_doctor_counts_an_adapter_that_writes_only_hidden_paths(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    add_hidden_dropin(source)
    assert main(["build", "--source", str(source), "--target", "hid"], {}, tmp_path) == 0
    assert files_under(source / "dist" / "hid" / ".hidden")
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    out = capsys.readouterr().out
    assert "no build output" not in out
    assert "FAIL" not in out


def test_doctor_names_a_stale_adapter_that_writes_only_hidden_paths(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    add_hidden_dropin(source)
    add_dropin(source, "echo")
    assert main(["build", "--source", str(source), "--target", "hid", "--target", "echo"], {}, tmp_path) == 0
    now = time.time()
    for path in files_under(source / "dist"):
        os.utime(path, (now - 100, now - 100))
    os.utime(source / "base" / "rules.md", (now - 50, now - 50))
    assert main(["build", "--source", str(source), "--target", "echo"], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    fails = [line for line in capsys.readouterr().out.splitlines() if line.startswith("FAIL")]
    assert any("dist/hid" in line for line in fails)
    assert not any("dist/echo" in line for line in fails)


def test_doctor_fails_before_the_first_build(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("FAIL") and "dist" in line and "build" in line for line in out.splitlines())


def test_doctor_lists_dropin_adapters(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    first = add_dropin(source, "echo")
    second = add_dropin(source, "other")
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    out = capsys.readouterr().out
    assert str(first) in out and str(second) in out
    assert out.splitlines().count(DROPIN_LINE) == 1


def test_doctor_without_dropins_has_no_dropin_line(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 0
    assert DROPIN_LINE not in capsys.readouterr().out


def test_doctor_fails_on_a_broken_dropin(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    (source / "adapters").mkdir()
    (source / "adapters" / "bad.py").write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    assert "bad.py" in capsys.readouterr().out


def test_doctor_reports_unresolved_secret_name_without_values(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    (source / "secrets.ref").write_text("SET_ONE=env\nMISSING_ONE=env\n", encoding="utf-8")
    env = {"SET_ONE": SECRET_VALUE}
    assert main(["build", "--source", str(source)], env, tmp_path) == 0
    capsys.readouterr()
    assert main(["doctor", "--source", str(source)], env, tmp_path) == 1
    out = capsys.readouterr().out
    assert any(line.startswith("FAIL") and "MISSING_ONE" in line for line in out.splitlines())
    assert any(line.startswith("ok") and "SET_ONE" in line for line in out.splitlines())
    assert SECRET_VALUE not in out


def test_doctor_fails_on_an_invalid_secrets_ref(tmp_path, capsys):
    source = make_ready_source(tmp_path)
    (source / "secrets.ref").write_text("not a valid line\n", encoding="utf-8")
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    assert "secrets.ref" in capsys.readouterr().out


@pytest.mark.skipif(os.name != "posix", reason="uses shell scripts as fake tools")
def test_doctor_discards_secret_manager_output(tmp_path, capfd, monkeypatch):
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for tool, code in (("op", 0), ("security", 1)):
        script = fakebin / tool
        script.write_text("#!/bin/sh\necho %s\necho %s >&2\nexit %d\n" % (SECRET_VALUE, SECRET_VALUE, code))
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", "%s%s%s" % (fakebin, os.pathsep, os.environ.get("PATH", "")))
    source = make_ready_source(tmp_path)
    (source / "secrets.ref").write_text(
        "FROM_OP=op://vault/item/field\nFROM_KEYCHAIN=keychain:my-item\n", encoding="utf-8"
    )
    assert main(["build", "--source", str(source)], {}, tmp_path) == 0
    capfd.readouterr()
    assert main(["doctor", "--source", str(source)], {}, tmp_path) == 1
    captured = capfd.readouterr()
    assert SECRET_VALUE not in captured.out + captured.err
    lines = captured.out.splitlines()
    assert any(line.startswith("ok") and "FROM_OP" in line for line in lines)
    assert any(line.startswith("FAIL") and "FROM_KEYCHAIN" in line for line in lines)


# --- end to end and misc ------------------------------------------------


def test_init_then_build_produces_agents_md(tmp_path):
    assert main(["init"], {}, tmp_path) == 0
    assert main(["build", "--target", "agents-md"], {}, tmp_path) == 0
    text = (tmp_path / "dist" / "agents-md" / "AGENTS.md").read_text(encoding="utf-8")
    assert text.strip()
    assert parse(SOURCE_FILES["base/rules.md"])[1].strip().splitlines()[0] in text


def test_help_lists_the_three_commands(capsys):
    assert main(["--help"], {}, Path(".")) == 0
    out = capsys.readouterr().out
    for command in ("init", "build", "doctor"):
        assert command in out


def test_secret_template_and_gitignore_content():
    assert all(
        line.startswith("#") or not line.strip() for line in SOURCE_FILES["secrets.ref"].splitlines()
    )
    assert SOURCE_FILES["secrets.ref"].strip()
    assert SOURCE_FILES[".gitignore"].splitlines() == ["dist/", "local/paths.env"]
    keys = read_paths_env_from_text(SOURCE_FILES["local/paths.env.example"])
    assert set(keys) == {"AGENT_DOTENV_LAYERS", "VAULT_PATH", "DEVICE_NAME"}
    assert set(SOURCE_FILES) == {
        "base/rules.md", "base/identity.md", "local/paths.env.example", "secrets.ref", ".gitignore",
    }


def read_paths_env_from_text(text: str) -> dict:
    return {
        line.partition("=")[0]: line.partition("=")[2]
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    }
