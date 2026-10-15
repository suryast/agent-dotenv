# Minimal example

A source folder made by `agent-dotenv init`, plus one drop-in adapter.

- `base/rules.md` and `base/identity.md` are the starter files from `init`.
- `adapters/plain_text.py` is a drop-in adapter named `plain-text`. It writes the rules body to `dist/plain-text/notes.txt`.
- `local/paths.env.example` is committed. `local/paths.env` is not part of the example.

Build it from this folder:

```bash
agent-dotenv build
```

The output goes to `dist/`, which is not committed. You get `dist/agents-md/AGENTS.md`, `dist/claude-ai-project/`, `dist/claude-code/`, `dist/cursor/` and `dist/plain-text/notes.txt`.

The drop-in adapter runs as ordinary Python with your permissions. Read it before you build a source folder that you did not write. See `docs/adapters.md` in the tool repository for how to write one.
