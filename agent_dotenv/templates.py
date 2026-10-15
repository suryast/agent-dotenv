"""Starter file text written by `init`. Python 3.9 compatible, stdlib only."""
from __future__ import annotations

from typing import Dict

SOURCE_FILES: Dict[str, str] = {
    "base/rules.md": """\
---
scope: personal
---
# Rules

- Keep answers short and direct.
- Ask before deleting files.
""",
    "base/identity.md": """\
---
scope: personal
---
# Identity

- I write in plain language.
- I prefer small, reviewable changes.
""",
    "local/paths.env.example": """\
# Absolute paths of external layer folders, separated by ":". An empty value in the process environment falls through to this file.
AGENT_DOTENV_LAYERS=
# Absolute path of your notes folder, if you have one.
VAULT_PATH=
# A short name for this computer.
DEVICE_NAME=
""",
    "secrets.ref": """\
# One NAME=source line per secret. The source is env, keychain:<item> or op://<reference>.
""",
    ".gitignore": """\
dist/
local/paths.env
""",
}

LAYER_FILES: Dict[str, str] = {
    "glossary.md": """\
---
scope: external
description: Terms and abbreviations used in this organisation.
---
# Glossary
""",
    "repos.md": """\
---
scope: external
description: The code repositories and what each one holds.
---
# Repositories
""",
    "tools.md": """\
---
scope: external
description: The tools the team uses and how to reach them.
---
# Tools
""",
    "people/README.md": """\
---
scope: external
description: Who is who in the organisation. Add one file per person.
---
# People
""",
}
