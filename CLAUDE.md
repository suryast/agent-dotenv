# CLAUDE.md

Guidance for contributors, human or AI, working in this repository.

## What this is

`agent_dotenv` builds per-agent instruction files (rules, identity, skills) from one layered Markdown source folder. Read [README.md](README.md) for the user view, [docs/adapters.md](docs/adapters.md) for the adapter interface and [docs/security.md](docs/security.md) for the secret and scope rules.

## Commands

Python 3.9, standard library only at runtime. Only `pytest` is needed for development.

```bash
python3 -m pytest -q
```

```bash
python3 -m pytest tests/test_layers.py::test_name -q
```

```bash
python3 -m agent_dotenv build --source examples/minimal
```

`pytest.ini` sets `pythonpath = .`. Without it `import agent_dotenv` fails.

## Layout

- `agent_dotenv/frontmatter.py`, `layers.py`: parse the `---` header, load, filter and resolve layers. The Claude Code adapter copies both flat into a plugin, so they import each other with `try: from .x import ... except ImportError: from x import ...`. Keep that form.
- `scan.py`: the secret scan. `adapters_api.py`: `BuildContext`, `AdapterOutput` and adapter discovery. `pipeline.py`: `run_build`. `cli.py`: `init`, `build`, `doctor`. `templates.py`: the files `init` writes.
- `agent_dotenv/adapters/`: the four built-in adapters. Register a new one in `adapters/__init__.py`.
- `examples/minimal/`: a source folder with one drop-in adapter. `tests/fixtures/source/`: the test source folder.

## Rules

- Start every module with `from __future__ import annotations`. Use `Optional[...]`, not `X | Y`, where a type is evaluated at runtime (Python 3.9). No `match`.
- Standard library only at runtime. No new dependency.
- Pipeline order matters: load layers, filter each layer, resolve, adapter build, secret scan, write. Filter each layer before resolve, with `resolve_filtered`. Never call `resolve` alone on unfiltered layers.
- The core (everything in `agent_dotenv/` outside `adapters/`) must not name a harness, not even in a comment. `tests/test_neutrality.py` fails if it does. Say "harness" or "adapter".
- An adapter returns data and never writes files. A build writes only under `dist/`.
- Never print a secret value. Findings carry file, line and kind only.
- Test tokens are built at runtime from fragments. Never commit a token-shaped literal.
- Public files hold no company name, personal email or home-directory path. The neutrality test checks this. Use placeholders such as `~/my-agent-env`.
- Built-in hooks exit 0 on every error.

## Git

Do not commit to `main`. Work on a branch, run `python3 -m pytest -q`, then open a pull request. Use commit subjects like `feat: ...`, `fix: ...`, `docs: ...`. Do not push without being asked.
