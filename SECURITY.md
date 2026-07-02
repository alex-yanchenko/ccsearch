# Security Policy

## Reporting a vulnerability

Email **oleksandr.yanchenko.ca@gmail.com** with the details and, where possible, a
reproduction. Please do **not** open a public issue for a security report.

## Threat model

ccfind is a local, read-only developer tool. It reads your Claude Code session
transcripts under `~/.claude/projects/` (or `$CLAUDE_CONFIG_DIR`), builds a text
cache under `~/.cache/ccfind/`, and shells out to `rg` and `fzf` to search and
browse them. It makes **no network calls** and sends nothing to any third party.
The only action it takes on your behalf is launching `claude --resume <id>` for a
session you explicitly select.
