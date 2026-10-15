# Smoke test results

Date: 2026-10-15. Claude Code 2.1.300 (the version installed when this file was written), macOS, Python 3.9.6. Commit tested: the merge that holds the final fix wave.

## 1. Clean install, init, build, doctor

Run in a fresh virtual environment, with the package installed from a local checkout (`pip install <checkout>`), in an empty temporary folder:

- `agent-dotenv --help`: exit 0.
- `agent-dotenv init`: wrote the starter files, exit 0.
- `agent-dotenv build`: built `agents-md` (1 file), `claude-ai-project` (1 file), `claude-code` (8 files) and `cursor` (2 files), exit 0.
- `agent-dotenv doctor`: every line ok, exit 0.

## 2. Claude Code loads the built plugin

Method: `claude -p <prompt> --plugin-dir dist/claude-code` from an unrelated directory.

- `claude plugin validate dist/claude-code` passed. The only warning is that `author` is not set.
- The hook run by hand (`python3 loader/session_start.py` with `CLAUDE_PLUGIN_ROOT` set) printed the expected `additionalContext` JSON and exited 0.
- A session with the plugin loaded quoted the exact rules bullet list from the starter `rules.md` when asked whether a given sentence was in its context. The SessionStart hook delivers its context.
- Lesson: the injected text does not name its source. A first prompt that asked for text "given by the agent-dotenv plugin" got the answer `NOT DELIVERED`. Ask about the content itself, not its source.

Limits of this test: one Claude Code version, `--plugin-dir` only (not a marketplace install), headless mode only.

## 3. Not checked

- A live Cursor session reading `.cursor/rules/*.mdc`. The file format was checked against Cursor's published documentation during review, not in the application.
- A live Codex or other `AGENTS.md` reader. `AGENTS.md` is plain Markdown.
- Pasting `project-instructions.md` into a Claude.ai project, and the real size limit of that field. The 8,000-character warning is a context budget, not a verified limit.
- Windows, macOS versions other than the one used, Python versions above 3.9 for the full suite. The hook was run by hand on newer Pythons during review.

## 4. Test suite

`python3 -m pytest -q`: 269 passed, 1 skipped (the skip needs Python 3.11 or newer).
