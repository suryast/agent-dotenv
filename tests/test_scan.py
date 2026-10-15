import pytest

from agent_dotenv.scan import Finding, read_secrets_ref, scan

# Planted strings are built at runtime so this file holds no token-shaped literal.
PLANTED = {
    "ghp": "ghp_" + "a" * 36,
    "github_pat": "github_pat_" + "B" * 22,
    "slack": "xox" + "b-" + "1234567890-abc",
    "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
    "sk": "sk-" + "x" * 24,
    "private_key": "-----BEGIN RSA PRIVATE" + " KEY-----",
}


@pytest.mark.parametrize("name", sorted(PLANTED))
def test_each_pattern_detected(name):
    files = {"clean.md": "nothing here\n", "dirty.md": "line one\nvalue: %s\n" % PLANTED[name]}
    findings = scan(files, [], {})
    assert len(findings) == 1
    assert findings[0].file == "dirty.md"
    assert findings[0].line == 2
    assert findings[0].kind == "pattern:%s" % name


def test_secret_ref_value_detected():
    env = {"GH_TOKEN": "s3cr3t-value-123"}
    findings = scan({"a.md": "x\nuse s3cr3t-value-123 here\n"}, ["GH_TOKEN"], env)
    assert findings == [Finding(file="a.md", line=2, kind="secret-ref:GH_TOKEN")]


def test_secret_ref_value_is_trimmed_before_matching():
    env = {"GH_TOKEN": "  s3cr3t-value-123\n"}
    findings = scan({"a.md": "use s3cr3t-value-123 here\n"}, ["GH_TOKEN"], env)
    assert findings == [Finding(file="a.md", line=1, kind="secret-ref:GH_TOKEN")]


def test_finding_never_contains_value():
    env = {"GH_TOKEN": "s3cr3t-value-123"}
    text = "s3cr3t-value-123 and %s\n" % PLANTED["ghp"]
    findings = scan({"a.md": text}, ["GH_TOKEN"], env)
    assert findings
    for finding in findings:
        assert "s3cr3t-value-123" not in repr(finding)
        assert PLANTED["ghp"] not in repr(finding)


def test_empty_short_and_whitespace_values_ignored():
    text = "abc and plenty of ordinary text        \n"
    env = {"E": "", "S": "abc", "W": " " * 8}
    assert scan({"a.md": text}, ["E", "S", "W"], env) == []


def test_unset_secret_name_ignored():
    assert scan({"a.md": "text\n"}, ["MISSING"], {}) == []


def test_sk_inside_a_word_is_not_a_key():
    assert scan({"a.md": "task-management-and-prioritisation-notes\n"}, [], {}) == []


def test_sk_at_start_of_line_is_a_key():
    findings = scan({"a.md": PLANTED["sk"] + "\n"}, [], {})
    assert [f.kind for f in findings] == ["pattern:sk"]


def test_bad_secrets_ref_line_raises(tmp_path):
    path = tmp_path / "secrets.ref"
    path.write_text("# comment\nGOOD=env\nBAD=plaintext-value\n")
    with pytest.raises(ValueError, match="line 3"):
        read_secrets_ref(path)


def test_read_secrets_ref_valid_and_missing(tmp_path):
    path = tmp_path / "secrets.ref"
    path.write_text("# c\n\nA=env\nB=keychain:item\nC=op://vault/item\n")
    assert read_secrets_ref(path) == {"A": "env", "B": "keychain:item", "C": "op://vault/item"}
    assert read_secrets_ref(tmp_path / "missing") == {}
