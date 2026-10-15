from __future__ import annotations

import shutil
from pathlib import Path

FIXTURE_SOURCE = Path(__file__).parent / "fixtures" / "source"


def make_source(tmp_path: Path) -> Path:
    """Copy the fixture source tree to tmp_path/source and return it."""
    dest = tmp_path / "source"
    shutil.copytree(FIXTURE_SOURCE, dest)
    return dest
