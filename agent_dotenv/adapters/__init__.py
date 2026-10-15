"""Built-in adapters. Tasks 6 to 9 register their modules in BUILTIN."""
from __future__ import annotations

from . import agents_md
from . import claude_ai_project
from . import cursor

BUILTIN: tuple = (
    agents_md,
    claude_ai_project,
    cursor,
)
