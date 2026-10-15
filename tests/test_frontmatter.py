from __future__ import annotations

import pytest

from agent_dotenv.frontmatter import FrontmatterError, Meta, parse, serialize


def test_parses_defaults():
    meta, body = parse("---\nscope: personal\n---\nhello\n")
    assert meta == Meta(scope="personal", mode="replace", targets=None, description="")
    assert meta.targets is None
    assert body == "hello\n"


def test_parses_all_keys():
    text = (
        "---\nscope: external\nmode: append\n"
        "targets: [alpha, beta-2]\ndescription: Acme terms\n---\nbody\n"
    )
    meta, body = parse(text)
    assert meta.scope == "external"
    assert meta.mode == "append"
    assert meta.targets == ("alpha", "beta-2")
    assert meta.description == "Acme terms"
    assert body == "body\n"


def test_missing_scope_raises():
    with pytest.raises(FrontmatterError, match="scope"):
        parse("---\nmode: replace\n---\nbody\n")


def test_no_frontmatter_raises():
    with pytest.raises(FrontmatterError, match="opening"):
        parse("just text\n")


def test_unknown_key_raises():
    with pytest.raises(FrontmatterError, match="colour"):
        parse("---\nscope: personal\ncolour: red\n---\nbody\n")


def test_bad_scope_raises():
    with pytest.raises(FrontmatterError, match="employer"):
        parse("---\nscope: employer\n---\nbody\n")


@pytest.mark.parametrize(
    "header",
    [
        "mode: merge",
        "targets: alpha",
        "targets: []",
        "targets: [Alpha]",
        "targets: [1abc]",
        "targets: [a b]",
        "targets: [a,, b_c]",
    ],
)
def test_bad_mode_and_targets_shape_raise(header):
    with pytest.raises(FrontmatterError):
        parse("---\nscope: personal\n%s\n---\nbody\n" % header)


def test_unclosed_fence_raises():
    with pytest.raises(FrontmatterError, match="closing"):
        parse("---\nscope: personal\nbody without a close\n")


def test_bom_and_crlf_accepted():
    text = "﻿---\r\nscope: personal\r\n---\r\nline one\r\nline two\r\n"
    meta, body = parse(text)
    assert meta.scope == "personal"
    assert body == "line one\nline two\n"


def test_dashes_in_body_not_a_fence():
    text = "---\nscope: personal\n---\nabove\n---\nbelow\n"
    meta, body = parse(text)
    assert meta.scope == "personal"
    assert body == "above\n---\nbelow\n"


@pytest.mark.parametrize(
    "meta",
    [
        Meta(scope="personal"),
        Meta(scope="sensitive", mode="append", targets=("a", "b-c")),
        Meta(scope="external", description="Acme terms"),
        Meta(scope="personal", targets=None, description="x: y"),
    ],
)
def test_serialize_roundtrip(meta):
    body = "line\n---\nmore\n"
    assert parse(serialize(meta, body)) == (meta, body)


def test_serialize_omits_targets_line_when_none():
    text = serialize(Meta(scope="personal"), "body\n")
    assert "targets" not in text
    assert text == "---\nscope: personal\nmode: replace\n---\nbody\n"
