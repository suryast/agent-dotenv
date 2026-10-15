"""Built-in adapters. Tasks 6 to 9 register their modules in BUILTIN."""
from __future__ import annotations

from . import claude_code

BUILTIN: tuple = (
    claude_code,
)
