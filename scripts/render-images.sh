#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
out="$root/docs/images"
build="$(mktemp -d)"
session="ccsearch-images-$$"
trap 'tmux kill-session -t "$session" 2>/dev/null || true; rm -rf "$build"' EXIT
chrome="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"

[ -x "$chrome" ] || { echo "Google Chrome not found at $chrome; set CHROME_PATH" >&2; exit 1; }
for tool in uv uvx tmux fzf rg; do
  command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }
done

config="$build/config"
frames="$build/frames"
mkdir -p "$config" "$frames" "$build/home"
cp -R "$root/scripts/images/demo-sessions/projects" "$config/"
cp "$root"/scripts/images/frames.{html,css,js} "$frames/"

uv sync --project "$root" --quiet
ccsearch="$root/.venv/bin/ccsearch"
demo_env=(env HOME="$build/home" CLAUDE_CONFIG_DIR="$config" CC_PROJ_STRIP="-Users-sam-code-" TERM=xterm-256color)

uv run --project "$root" python -c '
import os, sys, time
pairs = sys.argv[1:]
for path, hours in zip(pairs[::2], pairs[1::2]):
    moment = time.time() - float(hours) * 3600
    os.utime(path, (moment, moment))
' \
  "$config/projects/-Users-sam-code-acme-storefront/2f6c1d0e-8a41-4c7b-9e2d-5b3a7f10c214.jsonl" 2 \
  "$config/projects/-Users-sam-code-acme-storefront/c4a9e7f3-1b28-4d6e-8f05-93d2b6e1a230.jsonl" 26 \
  "$config/projects/-Users-sam-code-dotfiles/5a8c2e7d-6f14-4b93-b0a2-d17e4f9c3355.jsonl" 50 \
  "$config/projects/-Users-sam-code-acme-billing/9d3f6a18-5e7c-4b21-a4d0-6c8e1f2b0077.jsonl" 98 \
  "$config/projects/-Users-sam-code-acme-storefront/7b1e4c92-3d5f-4a08-b6c1-0e9f2a4d8198.jsonl" 170 \
  "$config/projects/-Users-sam-code-acme-billing/e1b70c45-92a6-4f3d-8e19-2a5d7c6b0081.jsonl" 240

wait_for_screen() {
  local text="$1" tries=0
  until tmux capture-pane -t "$session" -p | grep -q "$text"; do
    tries=$((tries + 1))
    if [ "$tries" -gt 100 ]; then
      echo "the ccsearch screen never showed '$text':" >&2
      tmux capture-pane -t "$session" -p >&2
      exit 1
    fi
    sleep 0.1
  done
}

capture() {
  local name="$1"
  tmux capture-pane -t "$session" -e -p | uvx --from ansi2html==1.9.5 ansi2html --inline --scheme=dracula >"$frames/$name.html"
  tmux kill-session -t "$session"
}

tmux new-session -d -s "$session" -x 150 -y 30 "${demo_env[*]} $ccsearch"
wait_for_screen "▸"
tmux send-keys -t "$session" -l "rate limit"
wait_for_screen "3/3"
wait_for_screen "Retry-After"
capture browser

tmux new-session -d -s "$session" -x 150 -y 22 "${demo_env[*]} $ccsearch 'rate limit'; sleep 30"
wait_for_screen "claude --resume 9d3f6a18"
capture search

shoot() {
  local size="$1" name="$2"
  if ! "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --allow-file-access-from-files --virtual-time-budget=6000 --window-size="$size" \
    --screenshot="$frames/$name.png" "file://$frames/frames.html#$name" >"$build/chrome.log" 2>&1 ||
    [ ! -s "$frames/$name.png" ]; then
    echo "Chrome did not write $name.png:" >&2
    cat "$build/chrome.log" >&2
    exit 1
  fi
}

shoot 1600,840 hero
shoot 1600,640 search
shoot 1280,640 social

mkdir -p "$out"
for name in hero search social; do
  cp "$frames/$name.png" "$out/$name.png"
  echo "wrote docs/images/$name.png"
done
