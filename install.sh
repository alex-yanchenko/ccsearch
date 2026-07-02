#!/usr/bin/env bash
# ccfind installer: check dependencies, then copy the script to ~/.local/bin.
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="${HOME}/.local/bin"

# python3 (3.7+) and ripgrep are required; fzf is only needed for the interactive browser.
if ! command -v python3 >/dev/null 2>&1; then
	echo "ccfind needs python3 (3.7+). Install it and re-run ./install.sh" >&2
	exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 7) else 1)'; then
	echo "ccfind needs python3 >= 3.7 (found $(python3 -V 2>&1)). Upgrade and re-run." >&2
	exit 1
fi
if ! command -v rg >/dev/null 2>&1; then
	echo "ccfind needs ripgrep (rg). Install it (macOS: brew install ripgrep) and re-run." >&2
	exit 1
fi
command -v fzf >/dev/null 2>&1 || \
	echo "note: fzf not found — 'ccfind <keyword>' works, but the interactive browser needs it (brew install fzf)." >&2

mkdir -p "$BIN"
install -m 0755 "$DIR/ccfind" "$BIN/ccfind"
echo "installed ccfind → $BIN/ccfind"

case ":$PATH:" in
	*":$BIN:"*) ;;
	*) echo "note: $BIN is not on your PATH — add this to your shell rc:" >&2
	   echo '  export PATH="$HOME/.local/bin:$PATH"' >&2 ;;
esac
echo "run 'ccfind' to start (the first run builds a cache)."
