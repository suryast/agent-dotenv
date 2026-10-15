from __future__ import annotations

from pathlib import Path

from agent_dotenv.adapters import cursor
from agent_dotenv.adapters_api import BuildContext
from agent_dotenv.frontmatter import Meta
from agent_dotenv.layers import Source
from agent_dotenv.pipeline import run_build
from tests.conftest import make_source
from tests.test_pipeline import dist_files, write_adapter, write_md

RULES = ".cursor/rules/agent-dotenv-rules.mdc"
IDENTITY = ".cursor/rules/agent-dotenv-identity.mdc"


def make_ctx(**bodies: str) -> BuildContext:
    sources = {
        key + ".md": Source(key=key + ".md", meta=Meta(scope="personal"), body=body, layer="base")
        for key, body in bodies.items()
    }
    return BuildContext(
        sources=sources,
        skills={},
        external_index={},
        external_roots=(),
        local_values={},
        source_dir=Path("."),
        options={},
    )


def test_two_rule_files_with_always_apply():
    out = cursor.build(make_ctx(rules="RULE_BODY\n", identity="IDENTITY_BODY\n"))
    assert sorted(out.files) == [IDENTITY, RULES]
    for rel, body in ((RULES, "RULE_BODY\n"), (IDENTITY, "IDENTITY_BODY\n")):
        text = out.files[rel]
        assert isinstance(text, str)
        head, sep, rest = text.partition("\n---\n")
        lines = head.splitlines()
        assert lines[0] == "---"
        assert sorted(line.split(":")[0] for line in lines[1:]) == ["alwaysApply", "description"]
        assert "alwaysApply: true" in lines
        assert any(
            line.startswith("description: ") and line[len("description: "):].strip()
            for line in lines
        )
        assert rest == body
    assert out.warnings == []


def test_missing_identity_writes_only_rules():
    out = cursor.build(make_ctx(rules="RULE_BODY\n"))
    assert list(out.files) == [RULES]


LAYERS_VAR = "AGENT_DOTENV_LAYERS"


def add_external_rules(source: Path) -> dict:
    """External layer file with the same key as a file the adapter reads."""
    write_md(
        source / "external_acme" / "rules.md",
        """
        ---
        scope: external
        mode: append
        ---
        EXT_MARKER_91bc
        """,
    )
    return {LAYERS_VAR: str(source / "external_acme")}


def add_sensitive_identity(source: Path) -> None:
    """Sensitive local file with the same key as a file the adapter reads."""
    write_md(
        source / "local" / "identity.md",
        """
        ---
        scope: sensitive
        ---
        SENS_MARKER_7f3a
        """,
    )


def test_no_external_or_sensitive_marker(tmp_path):
    source = make_source(tmp_path)
    env = add_external_rules(source)
    add_sensitive_identity(source)
    result = run_build(source, ["cursor"], env=env)
    assert result.ok, result.errors
    files = dist_files(source, "cursor")
    assert sorted(files) == [IDENTITY, RULES]
    assert b"FIXTURE_RULE" in files[RULES]
    assert b"FIXTURE_IDENTITY" in files[IDENTITY]
    assert not any(b"SENS_MARKER_7f3a" in data for data in files.values())
    assert not any(b"EXT_MARKER_91bc" in data for data in files.values())


def test_external_rules_are_refused(tmp_path):
    source = make_source(tmp_path)
    env = add_external_rules(source)
    result = run_build(source, ["cursor"], env=env)
    assert result.ok, result.errors
    files = dist_files(source, "cursor")
    assert b"FIXTURE_RULE" in files[RULES]
    assert not any(b"EXT_MARKER_91bc" in data for data in files.values())
    assert cursor.ACCEPTS_EXTERNAL is False
    assert cursor.NAME == "cursor"


def test_sensitive_identity_is_dropped(tmp_path):
    source = make_source(tmp_path)
    add_sensitive_identity(source)
    result = run_build(source, ["cursor"], env={})
    assert result.ok, result.errors
    files = dist_files(source, "cursor")
    assert b"FIXTURE_IDENTITY" in files[IDENTITY]
    assert b"FIXTURE_RULE" in files[RULES]
    assert not any(b"SENS_MARKER_7f3a" in data for data in files.values())


def test_targets_exclusion(tmp_path):
    source = make_source(tmp_path)
    rules = source / "base" / "rules.md"
    rules.write_text(
        "---\nscope: personal\ntargets: [other]\n---\nRULE_FOR_OTHER\n", encoding="utf-8"
    )
    write_adapter(source, "other", "return AdapterOutput(files={'x.txt': 'x'})")
    result = run_build(source, ["cursor"], env={})
    assert result.ok, result.errors
    assert sorted(dist_files(source, "cursor")) == [IDENTITY]
