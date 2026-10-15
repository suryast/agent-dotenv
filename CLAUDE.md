# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`agent_dotenv` builds per-harness agent instruction files (rules, identity, skills) from one layered Markdown source tree. It is a work in progress: the core library exists, but the build pipeline, built-in adapters, CLI and docs do not yet. The plan and design spec live outside this repo, in the private `agent-env` repo:

- Plan: `~/agent-flow/agent-env/docs/superpowers/plans/2026-10-15-agent-dotenv.md` (12 tasks; tasks 1-4 are done, 5-12 remain)
- Spec: `~/agent-flow/agent-env/docs/superpowers/specs/2026-10-15-agent-dotenv-design.md`
- Execution ledger and decisions: `.superpowers/sdd/2026-10-15-agent-dotenv/` (git-ignored; start with `read-this-first.md` and `progress.md`)

Read the plan task before implementing the next piece. Do not copy `base/`, `company/`, `local/` or `kb-scaffold/` content from `agent-env`; it holds personal and employer content.

## Commands

Python 3.9, standard library only at runtime. Only `pytest` is needed for development.

```bash
python3 -m pytest -q
```

```bash
python3 -m pytest tests/test_layers.py::test_name -q
```

`pytest.ini` sets `pythonpath = .`; without it `import agent_dotenv` fails. There is no build, lint or packaging config yet (planned in Task 10).

## Architecture

Pipeline (the order matters): **load layers → filter each layer → resolve → adapter build → secret scan → write to `dist/`**. Only the first four stages exist in code so far.

- `frontmatter.py`: line-based parser for the `---` header. `scope` is required (`personal | external | sensitive`). `mode` is `replace` (default) or `append`. `targets` is an optional list like `[a, b]`, and `None` means all adapters. Unknown keys raise `FrontmatterError`. `serialize` must omit the `targets` line when it is `None`.
- `layers.py`: loads one directory into `(sources, skills)`. Resolution order is `base/`, then external layers in listed order, then `local/`. A later layer replaces an earlier one by relative path, except `mode: append`, which concatenates bodies. External layers come from `AGENT_DOTENV_LAYERS` (colon-separated absolute paths, from the process env, else `local/paths.env`). Skills in external layers are ignored with a warning.
- `filter_sources` runs **per layer, before** `resolve`. This is deliberate: a dropped file (sensitive, external without permission, wrong target) must never leak into a later layer's `append` body, and a dropped override falls back to the earlier layer. Use `resolve_filtered`, not `resolve` alone.
- `scan.py`: secret scan on built output. Findings hold file, line and kind, and never the matched value. It checks fixed token patterns and the literal values of env vars named in `secrets.ref` (`NAME=env | keychain:<item> | op://<ref>`). Values under 8 characters are ignored.
- `adapters_api.py`: the adapter contract (`BuildContext`, `AdapterOutput`, `Adapter`) and `discover()`. Adapters load from the built-in `agent_dotenv.adapters.BUILTIN` tuple and from `<source>/adapters/*.py` drop-ins, never from external layers. A drop-in needs `NAME` (matches `^[a-z][a-z0-9-]*$`), `ACCEPTS_EXTERNAL` (bool) and `build(ctx)`. Files starting with `_` are skipped. Name clashes raise `AdapterError`.

## Constraints that tests or later tasks enforce

- Every module starts with `from __future__ import annotations`. Use `Optional[...]` where it is evaluated at runtime (Python 3.9).
- `layers.py` and `frontmatter.py` are copied flat into a plugin later, so they import each other with `try: from .x import ... except ImportError: from x import ...`. Keep that form.
- The core (everything in `agent_dotenv/` outside `adapters/`) must contain no harness names, not even in comments or docstrings. A neutrality test in Task 11 checks this. Built-in adapters register in `agent_dotenv/adapters/__init__.py`.
- Test fixtures must not hold real tokens. Build planted tokens at runtime. `tests/conftest.py::make_source` copies `tests/fixtures/source` into `tmp_path`.
- A build writes only under `dist/`. On a secret finding it deletes all output of the run and exits 1. Built-in hooks exit 0 on every error.

## Git

`main` is the working branch with all completed tasks; `v1` is a stale branch from the earlier plan (stops at Task 3). Remote `origin` is `git@github.com:suryast/agent-dotenv.git`. Commit after every task. Do not push without being asked.
