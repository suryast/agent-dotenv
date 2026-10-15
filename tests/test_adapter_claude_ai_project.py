from __future__ import annotations

from pathlib import Path

from agent_dotenv.adapters import claude_ai_project
from agent_dotenv.adapters_api import AdapterOutput, BuildContext
from agent_dotenv.frontmatter import Meta
from agent_dotenv.layers import Source
from agent_dotenv.pipeline import run_build
from tests.conftest import make_source

LAYERS_VAR = "AGENT_DOTENV_LAYERS"
TARGET = "claude-ai-project"


def source(key: str, body: str, layer: str = "base", scope: str = "personal") -> Source:
    return Source(key=key, meta=Meta(scope=scope), body=body, layer=layer)


def make_ctx(sources=None, external_index=None, options=None) -> BuildContext:
    return BuildContext(
        sources=sources or {},
        skills={},
        external_index=external_index or {},
        external_roots=(),
        local_values={},
        source_dir=Path("."),
        options=options or {},
    )


def out_dir(src: Path) -> Path:
    return src / "dist" / TARGET


def test_constants():
    assert claude_ai_project.NAME == "claude-ai-project"
    assert claude_ai_project.ACCEPTS_EXTERNAL is True


def test_instructions_rules_then_identity():
    ctx = make_ctx(
        sources={
            "identity.md": source("identity.md", "\nIDENTITY_TEXT\n\n"),
            "rules.md": source("rules.md", "RULES_TEXT\n"),
            "notes.md": source("notes.md", "NOTES_TEXT\n"),
        }
    )
    output = claude_ai_project.build(ctx)
    assert isinstance(output, AdapterOutput)
    assert output.files == {"project-instructions.md": "RULES_TEXT\n\nIDENTITY_TEXT\n"}
    assert output.warnings == []


def test_instructions_use_rules_whatever_their_layer(tmp_path):
    src = make_source(tmp_path)
    ext = src / "external_acme"
    (ext / "rules.md").write_text("---\nscope: external\n---\nEXT_RULES_MARKER\n", encoding="utf-8")
    result = run_build(src, [TARGET], env={LAYERS_VAR: str(ext)})
    assert result.ok, result.errors
    text = (out_dir(src) / "project-instructions.md").read_text(encoding="utf-8")
    assert "EXT_RULES_MARKER" in text
    assert "FIXTURE_RULE" not in text
    assert text.index("EXT_RULES_MARKER") < text.index("FIXTURE_IDENTITY")
    # The external rules.md is also an external file, so it is written to docs/ as a body.
    assert (out_dir(src) / "docs" / "rules.md").read_text(encoding="utf-8") == "EXT_RULES_MARKER\n"


def test_docs_only_with_active_external_layer(tmp_path):
    src = make_source(tmp_path)
    ext = src / "external_acme"
    result = run_build(src, [TARGET], env={LAYERS_VAR: str(ext)})
    assert result.ok, result.errors
    docs = out_dir(src) / "docs"
    names = sorted(p.relative_to(docs).as_posix() for p in docs.rglob("*") if p.is_file())
    assert names == ["glossary.md", "people/a.md"]
    assert "EXT_MARKER_91bc" in (docs / "glossary.md").read_text(encoding="utf-8")
    instructions = (out_dir(src) / "project-instructions.md").read_text(encoding="utf-8")
    assert "EXT_MARKER_91bc" not in instructions

    other = tmp_path / "other"
    other.mkdir()
    src2 = make_source(other)
    result = run_build(src2, [TARGET], env={})
    assert result.ok, result.errors
    assert not (out_dir(src2) / "docs").exists()
    assert not list(out_dir(src2).rglob("glossary.md"))
    assert "EXT_MARKER_91bc" not in (out_dir(src2) / "project-instructions.md").read_text(
        encoding="utf-8"
    )


def test_docs_are_bodies_without_frontmatter():
    ctx = make_ctx(
        sources={"rules.md": source("rules.md", "RULES_TEXT\n")},
        external_index={
            "glossary.md": source(
                "glossary.md", "GLOSSARY_BODY\n", layer="external", scope="external"
            ),
            "people/a.md": source(
                "people/a.md", "Alice works here.\n", layer="external", scope="external"
            ),
        },
    )
    files = claude_ai_project.build(ctx).files
    assert files["docs/glossary.md"] == "GLOSSARY_BODY\n"
    assert files["docs/people/a.md"] == "Alice works here.\n"
    assert not any("---" in str(v) for k, v in files.items() if k.startswith("docs/"))
    assert sorted(files) == ["docs/glossary.md", "docs/people/a.md", "project-instructions.md"]


def test_docs_from_fixture_have_no_frontmatter(tmp_path):
    src = make_source(tmp_path)
    result = run_build(src, [TARGET], env={LAYERS_VAR: str(src / "external_acme")})
    assert result.ok, result.errors
    glossary = (out_dir(src) / "docs" / "glossary.md").read_text(encoding="utf-8")
    assert glossary == "EXT_MARKER_91bc\n"
    assert "scope:" not in glossary
    assert "description:" not in glossary


def test_over_limit_warns_with_size():
    ctx = make_ctx(sources={"rules.md": source("rules.md", "x" * 8100)})
    output = claude_ai_project.build(ctx)
    assert output.warnings == [
        "project-instructions.md is 8101 characters, over the 8000 character limit"
    ]
    at_limit = make_ctx(sources={"rules.md": source("rules.md", "x" * 7999)})
    assert claude_ai_project.build(at_limit).warnings == []  # 7999 + newline = 8000, not over


def test_limit_from_options():
    sources = {"rules.md": source("rules.md", "RULES_TEXT")}
    output = claude_ai_project.build(make_ctx(sources=sources, options={"instructions_limit": "10"}))
    assert output.warnings == [
        "project-instructions.md is 11 characters, over the 10 character limit"
    ]
    big = make_ctx(
        sources={"rules.md": source("rules.md", "x" * 8100)},
        options={"instructions_limit": "9000"},
    )
    assert claude_ai_project.build(big).warnings == []


def test_bad_limit_option_uses_default_and_warns():
    sources = {"rules.md": source("rules.md", "x" * 8100)}
    output = claude_ai_project.build(
        make_ctx(sources=sources, options={"instructions_limit": "lots"})
    )
    assert len(output.warnings) == 2
    assert "lots" in output.warnings[0]
    assert output.warnings[1] == (
        "project-instructions.md is 8101 characters, over the 8000 character limit"
    )
    small = make_ctx(
        sources={"rules.md": source("rules.md", "RULES_TEXT")},
        options={"instructions_limit": "lots"},
    )
    warnings = claude_ai_project.build(small).warnings
    assert len(warnings) == 1 and "lots" in warnings[0]


def test_over_limit_warning_reaches_build_result(tmp_path):
    src = make_source(tmp_path)
    result = run_build(src, [TARGET], env={}, options={"instructions_limit": "10"})
    assert result.ok, result.errors
    assert len(result.warnings) == 1
    assert result.warnings[0].startswith("claude-ai-project: project-instructions.md is ")
    assert "over the 10 character limit" in result.warnings[0]


def test_no_sensitive_marker(tmp_path):
    src = make_source(tmp_path)
    # Sensitive files that the adapter reads (identity.md) and the sensitive base notes.md.
    (src / "base" / "identity.md").write_text(
        "---\nscope: sensitive\n---\nSENS_MARKER_7f3a identity\n", encoding="utf-8"
    )
    ext = src / "external_acme"
    (ext / "private.md").write_text(
        "---\nscope: sensitive\n---\nSENS_MARKER_7f3a doc\n", encoding="utf-8"
    )
    result = run_build(src, [TARGET], env={LAYERS_VAR: str(ext)})
    assert result.ok, result.errors
    files = [p for p in out_dir(src).rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert b"SENS_MARKER_7f3a" not in path.read_bytes()
    text = (out_dir(src) / "project-instructions.md").read_text(encoding="utf-8")
    assert "FIXTURE_RULE" in text
    assert "FIXTURE_IDENTITY" not in text
    assert not (out_dir(src) / "docs" / "private.md").exists()


def test_targets_exclusion(tmp_path):
    src = make_source(tmp_path)
    (src / "adapters").mkdir()
    (src / "adapters" / "other.py").write_text(
        "from agent_dotenv.adapters_api import AdapterOutput\n"
        "NAME = 'other'\n"
        "ACCEPTS_EXTERNAL = False\n"
        "def build(ctx):\n"
        "    return AdapterOutput(files={})\n",
        encoding="utf-8",
    )
    (src / "base" / "identity.md").write_text(
        "---\nscope: personal\ntargets: [other]\n---\nOTHER_ONLY_MARKER\n", encoding="utf-8"
    )
    result = run_build(src, [TARGET], env={})
    assert result.ok, result.errors
    text = (out_dir(src) / "project-instructions.md").read_text(encoding="utf-8")
    assert "OTHER_ONLY_MARKER" not in text
    assert "FIXTURE_RULE" in text


def test_stale_docs_removed(tmp_path):
    src = make_source(tmp_path)
    first = run_build(src, [TARGET], env={LAYERS_VAR: str(src / "external_acme")})
    assert first.ok, first.errors
    assert (out_dir(src) / "docs" / "glossary.md").exists()
    second = run_build(src, [TARGET], env={})
    assert second.ok, second.errors
    assert not (out_dir(src) / "docs").exists()
    assert (out_dir(src) / "project-instructions.md").exists()


def test_secret_in_external_file_name_fails_build(tmp_path):
    src = make_source(tmp_path)
    ext = src / "external_acme"
    token = "gh" + "p_" + "Q7" * 18  # built at runtime; no token literal in the repo
    (ext / ("notes-%s.md" % token)).write_text(
        "---\nscope: external\n---\nclean body\n", encoding="utf-8"
    )
    result = run_build(src, [TARGET], env={LAYERS_VAR: str(ext)})
    assert not result.ok
    assert ("%s/(output file names)" % TARGET, "pattern:ghp") in [
        (f.file, f.kind) for f in result.findings
    ]
    text = "\n".join(result.errors + result.warnings + [repr(f) for f in result.findings])
    assert token not in text
    assert not (src / "dist").exists()
