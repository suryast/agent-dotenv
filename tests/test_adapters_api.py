from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import agent_dotenv.adapters as adapters_pkg
from agent_dotenv.adapters_api import (
    Adapter,
    AdapterError,
    AdapterOutput,
    BuildContext,
    discover,
)

GOOD = '''NAME = "%s"
ACCEPTS_EXTERNAL = %s


def build(ctx):
    return None
'''


def write_dropin(source: Path, filename: str, text: str) -> Path:
    folder = source / "adapters"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_text(text, encoding="utf-8")
    return path


def fake_builtin(name: str) -> types.ModuleType:
    mod = types.ModuleType("fake_builtin_%s" % name.replace("-", "_"))
    mod.NAME = name
    mod.ACCEPTS_EXTERNAL = False
    mod.build = lambda ctx: AdapterOutput(files={})
    return mod


def test_discover_loads_dropin(tmp_path):
    path = write_dropin(tmp_path, "mine.py", GOOD % ("my-harness", "True"))
    found = discover(tmp_path)
    assert "my-harness" in found
    adapter = found["my-harness"]
    assert isinstance(adapter, Adapter)
    assert adapter.name == "my-harness"
    assert adapter.accepts_external is True
    assert adapter.origin == str(path)
    assert callable(adapter.build)
    assert "agent_dotenv_dropin_mine" not in sys.modules


def test_discover_without_adapters_folder(tmp_path):
    assert discover(tmp_path) == {}


def test_builtin_adapter_has_builtin_origin(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters_pkg, "BUILTIN", (fake_builtin("alpha"),))
    found = discover(tmp_path)
    assert found["alpha"].origin == "builtin"
    assert found["alpha"].accepts_external is False


def test_name_collision_with_builtin_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(adapters_pkg, "BUILTIN", (fake_builtin("alpha"),))
    path = write_dropin(tmp_path, "clash.py", GOOD % ("alpha", "False"))
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(path) in str(err.value)
    assert "alpha" in str(err.value)


def test_name_collision_between_dropins_fails(tmp_path):
    write_dropin(tmp_path, "a.py", GOOD % ("same", "False"))
    second = write_dropin(tmp_path, "b.py", GOOD % ("same", "False"))
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(second) in str(err.value)


def test_dropin_import_error_names_file(tmp_path):
    path = write_dropin(tmp_path, "broken.py", "import module_that_does_not_exist_xyz\n")
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(path) in str(err.value)


def test_dropin_syntax_error_names_file(tmp_path):
    path = write_dropin(tmp_path, "syntax.py", "def (:\n")
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(path) in str(err.value)


@pytest.mark.parametrize(
    "text",
    [
        'ACCEPTS_EXTERNAL = False\ndef build(ctx):\n    return None\n',
        'NAME = "x"\ndef build(ctx):\n    return None\n',
        'NAME = "x"\nACCEPTS_EXTERNAL = False\n',
        'NAME = "x"\nACCEPTS_EXTERNAL = False\nbuild = 3\n',
        'NAME = "x"\nACCEPTS_EXTERNAL = "yes"\ndef build(ctx):\n    return None\n',
    ],
)
def test_dropin_missing_build_or_name_fails(tmp_path, text):
    path = write_dropin(tmp_path, "incomplete.py", text)
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(path) in str(err.value)


@pytest.mark.parametrize("bad", ["Upper", "has space", "1leading", "", "under_score"])
def test_bad_name_pattern_fails(tmp_path, bad):
    path = write_dropin(tmp_path, "bad.py", GOOD % (bad, "False"))
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert str(path) in str(err.value)


def test_builtin_missing_name_names_module(tmp_path, monkeypatch):
    mod = types.ModuleType("fake_nameless")
    mod.ACCEPTS_EXTERNAL = False
    mod.build = lambda ctx: None
    monkeypatch.setattr(adapters_pkg, "BUILTIN", (mod,))
    with pytest.raises(AdapterError) as err:
        discover(tmp_path)
    assert "fake_nameless" in str(err.value)


def test_underscore_file_skipped(tmp_path):
    write_dropin(tmp_path, "_private.py", "raise RuntimeError('must not load')\n")
    write_dropin(tmp_path, "ok.py", GOOD % ("ok", "False"))
    found = discover(tmp_path)
    assert list(found) == ["ok"]


def test_non_python_files_ignored(tmp_path):
    write_dropin(tmp_path, "notes.txt", "raise RuntimeError('must not load')\n")
    assert discover(tmp_path) == {}


def test_adapters_dir_inside_external_layer_not_loaded(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    external = tmp_path / "external"
    marker = tmp_path / "marker.txt"
    write_dropin(
        external,
        "x.py",
        'from pathlib import Path\nPath(%r).write_text("ran")\n' % str(marker),
    )
    assert discover(source) == {}
    assert not marker.exists()


def test_dropins_do_not_leak_between_calls(tmp_path):
    write_dropin(tmp_path, "mine.py", GOOD % ("my-harness", "False"))
    first = discover(tmp_path)
    second = discover(tmp_path)
    assert first["my-harness"].build is not second["my-harness"].build


def test_dropin_with_dataclass_and_future_annotations_loads(tmp_path):
    text = (
        "from __future__ import annotations\n"
        "from dataclasses import dataclass\n"
        "@dataclass\n"
        "class Box:\n"
        "    value: int = 1\n"
        'NAME = "boxed"\n'
        "ACCEPTS_EXTERNAL = False\n"
        "def build(ctx):\n"
        "    return Box()\n"
    )
    write_dropin(tmp_path, "boxed.py", text)
    assert "boxed" in discover(tmp_path)


def test_dataclasses_shapes():
    out = AdapterOutput(files={"a": "b"})
    assert out.warnings == [] and out.scan_texts == {}
    other = AdapterOutput(files={})
    out.warnings.append("w")
    assert other.warnings == []
    ctx = BuildContext(
        sources={}, skills={}, external_index={}, external_roots=(),
        local_values={}, source_dir=Path("."), options={},
    )
    with pytest.raises(Exception):
        ctx.options = {}  # type: ignore[misc]
    adapter = Adapter(name="n", accepts_external=False, build=lambda c: out, origin="builtin")
    with pytest.raises(Exception):
        adapter.name = "m"  # type: ignore[misc]
