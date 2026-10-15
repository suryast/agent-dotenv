from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_dotenv.frontmatter import FrontmatterError, Meta
from agent_dotenv.layers import (
    Source,
    external_layer_dirs,
    filter_sources,
    load_layer,
    read_paths_env,
    resolve,
    resolve_filtered,
    validate_targets,
)
from tests.conftest import make_source

VAR = "AGENT_DOTENV_LAYERS"


def md(root: Path, rel: str, body: str, scope: str = "personal", **extra: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "".join("%s: %s\n" % (k, v) for k, v in extra.items())
    path.write_text("---\nscope: %s\n%s---\n%s" % (scope, head, body))


def skill(root: Path, name: str, files: dict) -> None:
    for rel, content in files.items():
        path = root / "skills" / name / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def test_load_layer_keys_and_skills(tmp_path):
    source = make_source(tmp_path)
    sources, skills = load_layer(source / "base", "base")
    assert set(sources) == {"rules.md", "identity.md", "notes.md"}
    assert sources["rules.md"].layer == "base"
    assert sources["rules.md"].meta.scope == "personal"
    assert set(skills) == {"demo"}
    assert "SKILL.md" in skills["demo"].files
    ext_sources, ext_skills = load_layer(source / "external_acme", "external")
    assert set(ext_sources) == {"glossary.md", "people/a.md"}
    assert ext_skills == {}


def test_missing_layer_root_is_empty(tmp_path):
    assert load_layer(tmp_path / "nope", "base") == ({}, {})
    assert load_layer(tmp_path / "nope", "external") == ({}, {})


def test_replace_later_layer_wins(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    md(a, "rules.md", "early")
    md(b, "rules.md", "late")
    sources, _ = resolve([load_layer(a, "base"), load_layer(b, "local")])
    assert sources["rules.md"].body == "late"
    assert sources["rules.md"].layer == "local"


def test_append_joins_with_blank_line(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    md(a, "rules.md", "early\n")
    md(b, "rules.md", "late\n", mode="append")
    sources, _ = resolve([load_layer(a, "base"), load_layer(b, "local")])
    assert sources["rules.md"].body == "early\n\nlate\n"


def test_append_across_three_layers_keeps_order(tmp_path):
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    md(a, "rules.md", "one\n")
    md(b, "rules.md", "two\n", mode="append", scope="external")
    md(c, "rules.md", "three\n", mode="append")
    layers = [load_layer(a, "base"), load_layer(b, "external"), load_layer(c, "local")]
    sources, _ = resolve(layers)
    assert sources["rules.md"].body == "one\n\ntwo\n\nthree\n"


def test_skill_dir_replaced_whole(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    skill(a, "demo", {"SKILL.md": "old", "extra.txt": "old extra"})
    skill(b, "demo", {"SKILL.md": "new"})
    _, skills = resolve([load_layer(a, "base"), load_layer(b, "local")])
    assert set(skills["demo"].files) == {"SKILL.md"}
    assert skills["demo"].files["SKILL.md"] == b"new"
    assert skills["demo"].layer == "local"


def test_external_layer_skills_ignored_with_warning(tmp_path):
    ext = tmp_path / "ext"
    md(ext, "glossary.md", "g", scope="external")
    skill(ext, "sneaky", {"SKILL.md": "x"})
    with pytest.warns(UserWarning, match="skills"):
        sources, skills = load_layer(ext, "external")
    assert "glossary.md" in sources
    assert "skills/sneaky/SKILL.md" not in sources
    assert skills == {}


def test_filter_drops_sensitive_always(tmp_path):
    md(tmp_path, "s.md", "x", scope="sensitive")
    sources, _ = load_layer(tmp_path, "base")
    assert filter_sources(sources, "any", True) == {}
    assert filter_sources(sources, "any", False) == {}


def test_filter_external_needs_permission(tmp_path):
    md(tmp_path, "e.md", "x", scope="external")
    md(tmp_path, "p.md", "x")
    sources, _ = load_layer(tmp_path, "external")
    assert set(filter_sources(sources, "any", False)) == {"p.md"}
    assert set(filter_sources(sources, "any", True)) == {"e.md", "p.md"}


def test_filter_respects_targets(tmp_path):
    md(tmp_path, "only_one.md", "x", targets="[one]")
    md(tmp_path, "both.md", "x")
    sources, _ = load_layer(tmp_path, "base")
    assert set(filter_sources(sources, "two", False)) == {"both.md"}
    assert set(filter_sources(sources, "one", False)) == {"both.md", "only_one.md"}


def test_resolve_filtered_drops_sensitive_base_before_append(tmp_path):
    base, local = tmp_path / "base", tmp_path / "local"
    md(base, "identity.md", "SECRET_BASE_TEXT", scope="sensitive")
    md(local, "identity.md", "local text", mode="append")
    layers = [load_layer(base, "base"), load_layer(local, "local")]
    sources, _ = resolve_filtered(layers, "any", False)
    assert sources["identity.md"].body == "local text"


def test_resolve_filtered_falls_back_when_override_dropped(tmp_path):
    base, ext = tmp_path / "base", tmp_path / "ext"
    md(base, "rules.md", "base rules")
    md(ext, "rules.md", "external override", scope="external")
    layers = [load_layer(base, "base"), load_layer(ext, "external")]
    sources, _ = resolve_filtered(layers, "any", False)
    assert sources["rules.md"].body == "base rules"
    sources, _ = resolve_filtered(layers, "any", True)
    assert sources["rules.md"].body == "external override"


def test_symlink_escape_skipped_for_files_and_skills(tmp_path):
    outside = tmp_path / "outside"
    md(outside, "secret.md", "outside text")
    leak = tmp_path / "leak.txt"
    leak.write_text("outside")
    root = tmp_path / "layer"
    md(root, "ok.md", "fine")
    skill(root, "demo", {"SKILL.md": "ok"})
    os.symlink(outside / "secret.md", root / "link.md")
    os.symlink(leak, root / "skills" / "demo" / "leak.txt")
    sources, skills = load_layer(root, "base")
    assert set(sources) == {"ok.md"}
    assert set(skills["demo"].files) == {"SKILL.md"}


def test_hidden_directories_skipped(tmp_path):
    md(tmp_path, "ok.md", "x")
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian" / "note.md").write_text("no frontmatter\n")
    skill(tmp_path, "demo", {"SKILL.md": "ok", ".git/config": "x", "sub/.obsidian/n.md": "x"})
    skill(tmp_path, ".trash", {"SKILL.md": "x"})
    sources, skills = load_layer(tmp_path, "base")
    assert set(sources) == {"ok.md"}
    assert set(skills) == {"demo"}
    assert set(skills["demo"].files) == {"SKILL.md"}


def test_hidden_files_skipped_in_skills_and_sources(tmp_path):
    md(tmp_path, "ok.md", "x")
    md(tmp_path, ".hidden.md", "HIDDEN_MARKER")
    md(tmp_path, "sub/.also-hidden.md", "HIDDEN_MARKER")
    skill(tmp_path, "demo", {"SKILL.md": "ok", ".DS_Store": "x", "sub/.keep": "x", "sub/ref.md": "y"})
    sources, skills = load_layer(tmp_path, "base")
    assert set(sources) == {"ok.md"}
    assert set(skills["demo"].files) == {"SKILL.md", "sub/ref.md"}


def test_strict_raises_with_path_nonstrict_skips(tmp_path):
    md(tmp_path, "good.md", "x")
    (tmp_path / "bad.md").write_text("no frontmatter here\n")
    with pytest.raises(FrontmatterError, match="bad.md"):
        load_layer(tmp_path, "base")
    sources, _ = load_layer(tmp_path, "base", strict=False)
    assert set(sources) == {"good.md"}


def test_non_utf8_strict_and_nonstrict(tmp_path):
    md(tmp_path, "good.md", "x")
    (tmp_path / "bin.md").write_bytes(b"---\nscope: personal\n---\n\xff\xfe\n")
    with pytest.raises(FrontmatterError, match="bin.md"):
        load_layer(tmp_path, "base")
    sources, _ = load_layer(tmp_path, "base", strict=False)
    assert set(sources) == {"good.md"}


def test_read_paths_env(tmp_path):
    p = tmp_path / "paths.env"
    p.write_text("# comment\n\nVAULT_PATH=/v\nDEVICE_NAME = \"mac\"\nbad line\n")
    assert read_paths_env(p) == {"VAULT_PATH": "/v", "DEVICE_NAME": "mac"}
    assert read_paths_env(tmp_path / "missing.env") == {}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "x").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir()
    two.mkdir()
    afile = tmp_path / "afile"
    afile.write_text("x")
    return {
        "home": home,
        "one": one,
        "two": two,
        "afile": afile,
        "missing": tmp_path / "missing",
    }


@pytest.mark.parametrize(
    "template, expected_keys, warnings_count",
    [
        ("{one}", ["one"], 0),
        ("{one}:{two}", ["one", "two"], 0),
        ("{two}:{one}", ["two", "one"], 0),
        ("{one}/", ["one"], 0),
        ("~/x", ["home/x"], 0),
        ("{one}::{two}", ["one", "two"], 1),
        ("{one}:{two}:", ["one", "two"], 1),
        ("{one}:relative/dir:{two}", ["one", "two"], 1),
        ("{one}:{missing}:{two}", ["one", "two"], 1),
        ("{one}:{afile}:{two}", ["one", "two"], 1),
        ("{one}:{two}:{one}/", ["one", "two"], 1),
        ("{missing}:{afile}:relative", [], 3),
    ],
)
def test_external_layer_dirs_forms(dirs, template, expected_keys, warnings_count):
    value = template.format(**{k: str(v) for k, v in dirs.items()})
    expected = [
        dirs["home"] / "x" if key == "home/x" else dirs[key] for key in expected_keys
    ]
    paths, warns = external_layer_dirs({VAR: value}, {})
    assert paths == expected
    assert len(warns) == warnings_count


def test_external_layer_dirs_unset_or_empty_is_silent():
    assert external_layer_dirs({}, {}) == ([], [])
    assert external_layer_dirs({VAR: ""}, {}) == ([], [])
    assert external_layer_dirs({}, {VAR: ""}) == ([], [])


def test_process_env_beats_paths_env(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    paths, _ = external_layer_dirs({VAR: str(a)}, {VAR: str(b)})
    assert paths == [a]
    paths, _ = external_layer_dirs({}, {VAR: str(b)})
    assert paths == [b]


def test_validate_targets_unknown_and_wrong_case_name_file_and_target(tmp_path):
    md(tmp_path, "ok.md", "x", targets="[known]")
    md(tmp_path, "nested/bad.md", "x", targets="[known, nope]")
    md(tmp_path, "any.md", "x")
    layers = [load_layer(tmp_path, "local")]
    with pytest.raises(FrontmatterError) as err:
        validate_targets(layers, ["known"])
    message = str(err.value)
    assert "nested/bad.md" in message
    assert "local" in message
    assert "nope" in message

    # Meta rejects uppercase at parse time, so build the Source by hand.
    bad = Source("case.md", Meta(scope="personal", targets=("Known",)), "x", "base")
    with pytest.raises(FrontmatterError) as err:
        validate_targets([({"case.md": bad}, {})], ["known"])
    message = str(err.value)
    assert "case.md" in message and "base" in message and "Known" in message

    validate_targets([], ["known"])
    good = Source("g.md", Meta(scope="personal", targets=("known",)), "x", "base")
    validate_targets([({"g.md": good}, {})], ["known"])
