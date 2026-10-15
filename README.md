# agent-dotenv

Write your agent rules, identity and skills once. Build them for any coding agent: AGENTS.md, Claude Code, Cursor and more. Layered, secret-safe, standard library only.

> **Status: work in progress.** The core library exists. The build pipeline, built-in adapters and the `init`, `build` and `doctor` commands do not exist yet. The usage section below describes the planned interface.

## Idea

`dotenv` keeps configuration in one file and loads it into any program. `agent-dotenv` does the same for agent setup. You keep rules, identity and skills in one portable folder. The tool builds the files that each coding agent reads.

Design goals:

- Switching an external layer (employer, client, team) changes only that layer's content.
- No file tagged `scope: sensitive` and no secret value appears in any output.
- Adding a harness takes one adapter file. The core contains no harness name.
- Python 3.9 or newer, standard library only at runtime.

## Source folder

Your content lives in a separate folder, usually a private repository.

```
my-agent-env/
  base/                 rules.md, identity.md, skills/<name>/SKILL.md, any other .md
  local/
    paths.env.example   committed
    paths.env           gitignored
  adapters/             optional drop-in adapters (*.py)
  secrets.ref           names and where each value lives, never values
  dist/                 build output, gitignored
```

Each Markdown file starts with frontmatter:

```
---
scope: personal | external | sensitive    required
mode: replace | append                     default replace
targets: [agents-md, claude-code]          default: all adapters
description: one line
---
```

## Layers

Later layers replace earlier layers by relative path. The order is `base/`, then external layers in listed order, then `local/`.

External layers are directories outside the source folder. Set them with `AGENT_DOTENV_LAYERS`, a list of absolute paths separated by `:`. The value comes from the process environment first, then from `local/paths.env`.

Each layer is filtered before the layers merge:

- `scope: sensitive` files are always dropped.
- `scope: external` files are dropped unless an external layer is active and the adapter accepts them.
- Files whose `targets` exclude the adapter are dropped.

A dropped file never merges into a later file with `mode: append`.

## Secret scan

Every output is scanned. The build fails on token-shaped strings (GitHub, Slack, AWS, `sk-` keys, private key headers). It also fails on the literal value of any environment variable named in `secrets.ref`. The report names the file and line, and never prints the value. On a finding, the build deletes all output of the run.

## Adapters

An adapter is a Python module with three names:

```python
NAME = "my-harness"
ACCEPTS_EXTERNAL = False

def build(ctx):  # returns AdapterOutput
    ...
```

Built-in adapters are planned for `agents-md`, `claude-code`, `cursor` and `claude-ai-project`. Drop-in adapters go in `<source>/adapters/*.py`. Files that start with `_` are skipped.

## Planned usage

```bash
agent-dotenv init
```

```bash
agent-dotenv build
```

`build` writes only under `dist/`. It never writes into your home directory.

## Development

```bash
python3 -m pytest -q
```

See [CLAUDE.md](CLAUDE.md) for the architecture and code constraints.
