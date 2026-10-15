from __future__ import annotations

from pathlib import Path

from agent_dotenv.adapters import agents_md
from agent_dotenv.adapters_api import AdapterOutput, BuildContext
from agent_dotenv.frontmatter import Meta
from agent_dotenv.layers import Skill, Source
from agent_dotenv.pipeline import run_build
from tests.conftest import make_source

LAYERS_VAR = "AGENT_DOTENV_LAYERS"


def source(key: str, body: str, layer: str = "base") -> Source:
    return Source(key=key, meta=Meta(scope="personal"), body=body, layer=layer)


def make_ctx(sources=None, skills=None) -> BuildContext:
    return BuildContext(
        sources=sources or {},
        skills=skills or {},
        external_index={},
        external_roots=(),
        local_values={},
        source_dir=Path("."),
        options={},
    )


def test_constants():
    assert agents_md.NAME == "agents-md"
    assert agents_md.ACCEPTS_EXTERNAL is False


def test_agents_md_has_rules_then_identity():
    ctx = make_ctx(
        sources={
            "identity.md": source("identity.md", "\nIDENTITY_TEXT\n\n"),
            "rules.md": source("rules.md", "RULES_TEXT\n"),
            "notes.md": source("notes.md", "NOTES_TEXT\n"),
        }
    )
    output = agents_md.build(ctx)
    assert isinstance(output, AdapterOutput)
    assert output.files == {"AGENTS.md": "RULES_TEXT\n\nIDENTITY_TEXT\n"}


def test_missing_file_is_skipped():
    ctx = make_ctx(sources={"rules.md": source("rules.md", "RULES_TEXT\n")})
    assert agents_md.build(ctx).files["AGENTS.md"] == "RULES_TEXT\n"
    ctx = make_ctx(sources={"identity.md": source("identity.md", "IDENTITY_TEXT\n")})
    assert agents_md.build(ctx).files["AGENTS.md"] == "IDENTITY_TEXT\n"


def test_skills_copied_and_listed():
    ctx = make_ctx(
        sources={"rules.md": source("rules.md", "RULES_TEXT\n")},
        skills={
            "demo": Skill(
                name="demo",
                files={"SKILL.md": b"---\nname: demo\n---\nbody\n", "ref/a.txt": b"\xff\x00"},
                layer="base",
            ),
            "other": Skill(name="other", files={"SKILL.md": b"x\n"}, layer="local"),
        },
    )
    files = agents_md.build(ctx).files
    assert files["skills/demo/SKILL.md"] == b"---\nname: demo\n---\nbody\n"
    assert files["skills/demo/ref/a.txt"] == b"\xff\x00"
    assert files["skills/other/SKILL.md"] == b"x\n"
    assert files["AGENTS.md"] == (
        "RULES_TEXT\n\n## Skills\n\n"
        "- skills/demo/SKILL.md\n"
        "- skills/other/SKILL.md\n"
    )


def test_no_skills_section_without_skills():
    ctx = make_ctx(sources={"rules.md": source("rules.md", "RULES_TEXT\n")})
    assert "## Skills" not in agents_md.build(ctx).files["AGENTS.md"]


def test_no_external_or_sensitive_marker(tmp_path):
    src = make_source(tmp_path)
    ext = src / "external_acme"
    (ext / "rules.md").write_text("---\nscope: external\n---\nEXT_MARKER_91bc\n", encoding="utf-8")
    result = run_build(src, ["agents-md"], env={LAYERS_VAR: str(ext)})
    assert result.ok, result.errors
    text = "\n".join(
        p.read_text(encoding="utf-8") for p in (src / "dist" / "agents-md").rglob("*") if p.is_file()
    )
    assert "EXT_MARKER_91bc" not in text
    assert "SENS_MARKER_7f3a" not in text
    assert "FIXTURE_RULE" in text


def test_targets_exclusion(tmp_path):
    src = make_source(tmp_path)
    # A target must name a known adapter, so register a drop-in named "other".
    (src / "adapters").mkdir()
    (src / "adapters" / "other.py").write_text(
        "from agent_dotenv.adapters_api import AdapterOutput\n"
        "NAME = 'other'\n"
        "ACCEPTS_EXTERNAL = False\n"
        "def build(ctx):\n"
        "    return AdapterOutput(files={})\n",
        encoding="utf-8",
    )
    (src / "base" / "extra.md").write_text(
        "---\nscope: personal\ntargets: [other]\n---\nOTHER_ONLY_MARKER\n", encoding="utf-8"
    )
    (src / "base" / "rules.md").write_text(
        "---\nscope: personal\ntargets: [other]\n---\nOTHER_RULES_MARKER\n", encoding="utf-8"
    )
    result = run_build(src, ["agents-md"], env={})
    assert result.ok, result.errors
    text = (src / "dist" / "agents-md" / "AGENTS.md").read_text(encoding="utf-8")
    assert "OTHER_RULES_MARKER" not in text
    assert "OTHER_ONLY_MARKER" not in text
    assert "FIXTURE_IDENTITY" in text


def test_end_to_end_via_run_build(tmp_path):
    src = make_source(tmp_path)
    ext = src / "external_acme"
    result = run_build(src, ["agents-md"], env={LAYERS_VAR: str(ext)})
    assert result.ok, result.errors
    assert result.errors == [] and result.findings == []
    out = src / "dist" / "agents-md"
    text = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert text.index("FIXTURE_RULE") < text.index("FIXTURE_IDENTITY")
    assert "SENS_MARKER_7f3a" not in text
    assert "EXT_MARKER_91bc" not in text
    assert "- skills/demo/SKILL.md" in text
    assert (out / "skills" / "demo" / "SKILL.md").read_bytes().startswith(b"---\nname: demo")
    assert sorted(p.name for p in (src / "dist").iterdir()) == ["agents-md"]
