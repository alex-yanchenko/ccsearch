# ccsearch

`ccsearch` searches your **Claude Code sessions by content** — so you can find which
of your many long-running chats discussed a ticket, PR, file, or idea, even weeks
later and even after the conversation drifted across topics.

Claude Code stores every session as a transcript under `~/.claude/projects/`.
`ccsearch` indexes the actual conversation (your messages + the AI's responses, plus
each session's title) — never the JSON metadata (uuids, timestamps, token counts,
tool input/output) — and gives you a fast fuzzy browser with a live preview and
one-key resume.

## Quick start

Prerequisites: **python3** (3.9+), **ripgrep** (`rg`), and **fzf** (only for the
interactive browser — `ccsearch <keyword>` works without it).

```bash
# macOS / Linux — Homebrew pulls in ripgrep + fzf for you
brew install alex-yanchenko/tap/ccsearch

# or, if you use uv / pipx (install ripgrep + fzf separately)
uvx ccsearch            # run without installing
pipx install ccsearch   # install for repeated use
```

Then run:

```bash
ccsearch
```

The first run builds a small text cache of your sessions (a few seconds); after
that it only re-indexes sessions that changed.

## Usage

```bash
ccsearch                  # interactive browser — type to search, Enter resumes the session
ccsearch <keyword>        # list sessions mentioning <keyword>, ranked
ccsearch --index [N]      # fingerprint the N most-recent sessions (title + tickets touched)
```

In the browser:

- **type** to live-search conversation text; the right pane previews the matched
  message in full with the surrounding context collapsed.
- **`Enter`** runs `claude --resume <id>` for the highlighted session.
- **`Ctrl-T`** cycles the search mode; **`Ctrl-S`** toggles the sort (date ⇄ matches).
- **`Ctrl-D` / `Ctrl-U`** (or the mouse) scroll the preview; **`Esc`** quits.

The current mode and sort show in the prompt, e.g. `anywhere · ⇅date ▸`.

### Search modes (`Ctrl-T`)

Multi-word queries are split on spaces; the mode controls how the words must match:

- **anywhere** — every word appears *somewhere* in the session (words may be in
  different messages).
- **one-msg** — every word appears together in a *single* message. The default.
- **exact** — the whole query matches as one literal phrase.

Each mode is a strict subset of the one before it. A single-word query behaves the
same in all three.

## How it works

Each session is indexed into a small structured cache (`~/.cache/ccsearch/<id>.txt`,
one message per line, plus a parallel `.meta` with role + timestamp). Both the
result ranking and the preview read this cache, so search is fast and accurate even
on very large transcripts. The cache excludes tool I/O, metadata, and
`<channel>`/`<command>` automation lines, so you only ever match real conversation.

The cache stores your conversation text in **plaintext** under `~/.cache/ccsearch/`.
It's derived from your existing Claude Code transcripts, makes no network calls, and
can be deleted at any time with `rm -rf ~/.cache/ccsearch` (your transcripts are untouched).

> AI *thinking* text is not searchable — Claude Code persists only a signature for
> thinking blocks, not the text.

## Environment variables

- `CLAUDE_CONFIG_DIR` — read sessions from `$CLAUDE_CONFIG_DIR/projects` if you
  relocated your Claude config.
- `CC_JIRA_PREFIXES` — ticket-key prefixes detected for the `--index` fingerprint.
  Default matches any Jira-style key (`[A-Z]{2,}-123`); set your own to restrict and
  keep lookalikes out, e.g. `export CC_JIRA_PREFIXES="ABC|XYZ"`.
- `CC_PROJ_STRIP` — pipe-separated workspace-dir prefixes trimmed from project labels
  (default `code-|src-|repos-|dev-|projects-`). Extend for your own layout.
- `NO_COLOR` — disable all color.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `command not found: ccsearch` | Brew install: run `brew link ccsearch`. pipx install: confirm `~/.local/bin` is on `PATH` (`pipx ensurepath`). |
| No results / browser falls back to a plain list | Install `ripgrep` and `fzf`. |
| "No sessions" | No Claude Code sessions yet, or config relocated — set `CLAUDE_CONFIG_DIR` to the dir containing `projects/`. |
| Stale or odd results | Delete the cache and let it rebuild: `rm -rf ~/.cache/ccsearch`. |
| Colors look wrong | Run `NO_COLOR=1 ccsearch`, or use a 256-color terminal. |

## License

[PolyForm Noncommercial 1.0.0](./LICENSE) — free for noncommercial use.
