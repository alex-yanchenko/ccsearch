#!/usr/bin/env python3
"""ccsearch — search your Claude Code sessions by CONTENT, not by name.

Claude Code stores every session as a transcript under ~/.claude/projects/. This greps
the actual conversation (your messages + AI responses) — never the JSON metadata
(uuids, timestamps, token counts, tool I/O) — so you can find which session discussed a
ticket / PR / file weeks later, even after the chat drifted across topics.

Requirements:
  • python3   (3.9+; macOS/Linux ship it)
  • ripgrep   (`rg`)   — brew install ripgrep   /   apt install ripgrep
  • fzf                — brew install fzf        /   apt install fzf   (only for the browser)

Install:
  • brew install alex-yanchenko/tap/ccsearch   (ripgrep + fzf come as dependencies)
  • or: uvx ccsearch   /   pipx install ccsearch   /   pip install ccsearch
  Then run `ccsearch` — the first run builds a text cache of your sessions (one-time, a few seconds).

Usage:
  ccsearch                     # interactive fzf browser: type to search bodies, enter resumes
  ccsearch <keyword>           # which sessions mention <keyword>, ranked by match count
  ccsearch --index [N]         # fingerprint the N most-recent sessions (title + tickets touched)

Env:
  CC_JIRA_PREFIXES="ABC|XYZ" # ticket-key prefixes for the fingerprint (default: any [A-Z]{2,}-123)
  CC_PROJ_STRIP="foo-|bar-"  # workspace dir prefixes to trim from project labels (default: code-|src-|…)
  CLAUDE_CONFIG_DIR=…        # read sessions from $CLAUDE_CONFIG_DIR/projects if you relocated it
  NO_COLOR=1                 # disable all color
"""

import datetime
import glob
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import textwrap
import time

ROOT = os.path.join(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")), "projects")
# Ticket-key prefixes for the --index fingerprint. Default matches any Jira-style key
# (e.g. ABC-123). Set CC_JIRA_PREFIXES="ABC|XYZ" to restrict to your projects and keep
# lookalikes (e.g. course codes like BIO-111) out.
PREFIXES = os.environ.get("CC_JIRA_PREFIXES", "[A-Z]{2,}")
TICKET = re.compile(rf"\b(?:{PREFIXES})-\d{{2,}}\b")

# ── style ────────────────────────────────────────────────────────────────
_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(code, s):
    return f"\033[{code}m{s}\033[0m" if _TTY else s


BOLD = lambda s: c("1", s)
DIM = lambda s: c("2", s)
CYAN = lambda s: c("36", s)
GREEN = lambda s: c("32", s)
YELLOW = lambda s: c("33", s)
MAGENTA = lambda s: c("35", s)


def rel_time(ts):
    d = time.time() - ts
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    if d < 86400 * 14:
        return f"{int(d // 86400)}d ago"
    return time.strftime("%b %d", time.localtime(ts))


def local_stamp(ts):
    """ISO-8601 UTC timestamp (…Z) → local-timezone 'MM-DD HH:MM'. 11-space pad if absent/bad."""
    if not ts:
        return " " * 11
    try:
        return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except Exception:
        return " " * 11


CHANNEL = re.compile(r'<channel\s+source="([^"]+)"(?:\s+event_type="([^"]+)")?')
COMMAND = re.compile(r"<command-name>\s*(\S+)")


def clean_label(label):
    """Turn channel/command transcript blobs into a short readable title."""
    m = CHANNEL.search(label)
    if m:
        src, evt = m.group(1), m.group(2)
        return f"⟨{src}{(' · ' + evt) if evt else ''}⟩"
    m = COMMAND.search(label)
    if m:
        return m.group(1)
    return label


def clean_snip(snip):
    """De-noise a raw JSONL snippet: unescape, collapse whitespace, trim quotes."""
    snip = snip.replace('\\"', '"').replace("\\n", " ").replace("\\t", " ")
    snip = re.sub(r"\s+", " ", snip).strip().strip(',"')
    return snip


def proj_of(path):
    # project dir name is the cwd path with non-alphanumerics → '-'; strip the encoded $HOME prefix
    name = os.path.basename(os.path.dirname(path))
    home = os.path.expanduser("~").replace("/", "-")
    return "~/" + name[len(home) :].lstrip("-") if name.startswith(home) else name


def is_session(path):
    return "/subagents/" not in path


# ── content cache ──────────────────────────────────────────────────────────
# We never grep raw .jsonl — it's full of uuids, timestamps, token/cache usage,
# tool I/O and other metadata. Instead we extract the real conversation
# (your messages + AI text + AI thinking) into a per-session text cache and
# search that. Rebuilt only when a session's transcript changes.
CACHE = os.path.expanduser("~/.cache/ccsearch")
MODE_FILE = os.path.join(CACHE, ".mode")
# Search modes (cycled with ^t in the browser):
#   session — every space-separated term appears somewhere in the session (AND)
#   message — every term appears together in a single message (default)
#   phrase  — the whole query matches as one literal substring
SEARCH_MODES = ["session", "message", "phrase"]


def get_mode():
    try:
        m = open(MODE_FILE).read().strip()
    except OSError:
        m = ""
    return m if m in SEARCH_MODES else "message"


def set_mode(m):
    os.makedirs(CACHE, exist_ok=True)
    with open(MODE_FILE, "w") as fh:
        fh.write(m)


def cycle_mode():
    m = SEARCH_MODES[(SEARCH_MODES.index(get_mode()) + 1) % len(SEARCH_MODES)]
    set_mode(m)
    return m


SORT_FILE = os.path.join(CACHE, ".sort")
SORTS = ["date", "matches"]  # date = most recent first (default); matches = by hit count, recency tiebreak


def get_sort():
    try:
        s = open(SORT_FILE).read().strip()
    except OSError:
        s = ""
    return s if s in SORTS else "date"


def set_sort(s):
    os.makedirs(CACHE, exist_ok=True)
    with open(SORT_FILE, "w") as fh:
        fh.write(s)


def toggle_sort():
    set_sort("matches" if get_sort() == "date" else "date")


def prompt_label():
    mode_word = {"session": "anywhere", "message": "one-msg", "phrase": "exact"}[get_mode()]
    return f"{mode_word} · ⇅{get_sort()} ▸ "


def iter_entries(lines):
    """Yield (role, ts, text) for conversational messages only — no tool I/O, no metadata,
    no <channel>/<command> machinery. role ∈ {you, cc, think}."""
    for ln in lines:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") not in ("user", "assistant"):
            continue
        is_user = o["type"] == "user"
        ts = o.get("timestamp")
        raw = o.get("message", {}).get("content")
        if isinstance(raw, str):
            if raw and not raw.lstrip().startswith("<"):  # skip <channel>/<command> machinery
                yield ("you", ts, raw)
            continue
        for p in raw if isinstance(raw, list) else []:
            if not isinstance(p, dict):
                continue
            kind = p.get("type")
            if (kind == "text" or (kind is None and "text" in p)) and p.get("text"):
                yield ("you" if is_user else "cc", ts, p["text"])
            elif kind == "thinking" and p.get("thinking"):
                yield ("think", ts, p["thinking"])


def text_cache(sid):
    return os.path.join(CACHE, sid + ".txt")


def meta_cache(sid):
    return os.path.join(CACHE, sid + ".meta")


def build_cache(src, sid):
    """Structured cache: one collapsed message per line in <sid>.txt (clean text for search),
    plus a parallel <sid>.meta line 'role\\tts'. One message per line so message/phrase modes
    and the preview work directly off the small cache — no re-parsing the raw transcript."""
    try:
        with open(src, errors="ignore") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return
    texts, metas = [], []
    # the AI-generated session title is searchable too — store it as the first line
    title = None
    for ln in lines:
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") == "ai-title":
            title = o.get("aiTitle")
    if title and title.strip():
        texts.append(" ".join(title.split()))
        metas.append("title\t")
    for role, ts, text in iter_entries(lines):
        one = " ".join(text.split())
        if not one:
            continue
        texts.append(one)
        metas.append(f"{role}\t{ts or ''}")
    # Write .meta first, .txt last: refresh_cache keys staleness off .txt, so a kill between
    # the two leaves .txt missing/older → clean rebuild, never a mismatched .txt/.meta pair.
    for path, body in ((meta_cache(sid), "\n".join(metas)), (text_cache(sid), "\n".join(texts))):
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            fh.write(body)
        os.replace(tmp, path)


def cache_entries(sid):
    """[(role, ts, text)] from a session's structured cache (small — read in full)."""
    try:
        texts = open(text_cache(sid), errors="ignore").read().split("\n")
        metas = open(meta_cache(sid), errors="ignore").read().split("\n")
    except OSError:
        return []
    out = []
    for one, m in zip(texts, metas):
        if not one:
            continue
        role, _, ts = m.partition("\t")
        out.append((role or "cc", one, ts or None))  # (role, text, ts) — matches preview unpacking
    return out


def refresh_cache(verbose=False):
    """Ensure each live session has an up-to-date structured cache. Returns {sid: src_path}."""
    os.makedirs(CACHE, exist_ok=True)
    srcs = {os.path.basename(f)[:-6]: f for f in glob.glob(f"{ROOT}/*/*.jsonl") if is_session(f)}
    stale = [
        (sid, f)
        for sid, f in srcs.items()
        if not os.path.exists(text_cache(sid))
        or not os.path.exists(meta_cache(sid))
        or os.path.getmtime(text_cache(sid)) < os.path.getmtime(f)
    ]
    if stale and verbose:
        print(DIM(f"ccsearch: indexing {len(stale)} session(s)…"), file=sys.stderr)
    for sid, f in stale:
        build_cache(f, sid)
    return srcs


def term_counts(term):
    """{sid: occurrences} for one literal, case-insensitive term over the text caches."""
    counts = {}
    try:
        out = subprocess.run(
            ["rg", "--count-matches", "-i", "-F", "--glob", "*.txt", term, CACHE],
            capture_output=True,
            text=True,
        ).stdout
    except FileNotFoundError:
        return counts
    for line in out.splitlines():
        path, _, c = line.rpartition(":")
        if path and c.isdigit():
            counts[os.path.basename(path)[:-4]] = int(c)
    return counts


def message_has_all(sid, terms_lower):
    """True if a single cached message line contains every term (reads the small text cache)."""
    try:
        with open(text_cache(sid), errors="ignore") as fh:
            for ln in fh:
                low = ln.lower()
                if all(t in low for t in terms_lower):
                    return True
    except OSError:
        pass
    return False


def matching(keyword, mode, srcs):
    """{sid: score} for sessions matching `keyword` under `mode`, restricted to live srcs.

      session — every space-separated term appears somewhere in the session (AND)
      message — every term appears together in a single message
      phrase  — the whole query matches as one literal substring
    A single token behaves the same in every mode (literal substring).
    """
    terms = keyword.split()
    if not terms:
        return {}
    if mode == "phrase":
        return {sid: c for sid, c in term_counts(keyword).items() if sid in srcs}
    per_term = [term_counts(t) for t in terms]
    common = set(per_term[0])
    for d in per_term[1:]:
        common &= d.keys()
    scores = {sid: sum(d.get(sid, 0) for d in per_term) for sid in common if sid in srcs}
    if mode == "message" and len(terms) > 1:
        tl = [t.lower() for t in terms]
        scores = {sid: s for sid, s in scores.items() if message_has_all(sid, tl)}
    return scores


def scan(path):
    """Return (latest_title, first_user_text, set_of_tickets) for one transcript."""
    title, first, tickets = None, None, set()
    try:
        with open(path, errors="ignore") as fh:
            for ln in fh:
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                t = o.get("type")
                if t == "ai-title":
                    title = o.get("aiTitle")
                elif t == "user" and first is None:
                    raw = o.get("message", {}).get("content")
                    txt = (
                        raw
                        if isinstance(raw, str)
                        else " ".join(p.get("text", "") for p in raw if isinstance(p, dict))
                    )
                    first = " ".join(txt.split())[:70]
                tickets.update(TICKET.findall(ln))
    except Exception:
        pass
    return title, first, tickets


def highlight(snip, terms):
    """Highlight each term in `terms` (a list). Allows a wrap break between characters so a
    long term (URL) still highlights when textwrap has split it across lines."""
    if not _TTY or not terms:
        return snip
    for term in terms:
        # whitespace in the term matches a run of any whitespace (incl. a wrap break)
        pat = r"(?:\n\s*)?".join(r"\s+" if ch.isspace() else re.escape(ch) for ch in term)
        snip = re.sub(f"({pat})", lambda m: YELLOW(m.group(1)), snip, flags=re.I)
    return snip


def find(keyword):
    if not os.path.isdir(ROOT):
        print(f"\n  {DIM('no Claude Code sessions under')} {BOLD(ROOT)} {DIM('(set CLAUDE_CONFIG_DIR?)')}\n")
        return
    if shutil.which("rg") is None:
        print(f"\n  {DIM('ripgrep (rg) not found — install it (macOS: brew install ripgrep)')}\n")
        return
    srcs = refresh_cache(verbose=True)
    counts = matching(keyword, "session", srcs)
    rows = []
    for sid, n in counts.items():
        f = srcs.get(sid)
        if not f:
            continue
        title, first, _ = scan(f)
        snip = ""
        try:
            alt = "|".join(re.escape(t) for t in keyword.split())
            s = (
                subprocess.run(
                    ["rg", "-i", "-m1", "-o", f".{{0,30}}(?:{alt}).{{0,45}}", text_cache(sid)],
                    capture_output=True,
                    text=True,
                )
                .stdout.strip()
                .splitlines()
            )
            snip = clean_snip(s[0]) if s else ""
        except Exception:
            pass
        rows.append(
            (
                n,
                os.path.getmtime(f),
                proj_of(f),
                sid,
                clean_label(title or first or "(empty)"),
                snip,
                session_cwd(f),
            )
        )
    # rank by match count, then recency
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)

    shown = keyword if len(keyword) <= 50 else "…" + keyword[-47:]
    if not rows:
        print(f"\n  {DIM('no sessions mention')} {BOLD(shown)}\n")
        return
    print(f"\n  {BOLD(str(len(rows)))} session(s) mention {YELLOW(shown)}\n")
    for i, (n, mtime, proj, sid, label, snip, cwd) in enumerate(rows, 1):
        hits = f"{n} match{'es' if n != 1 else ''}"
        print(f"  {CYAN(f'{i:>2}')}  {BOLD(label)}")
        print(
            f"      {YELLOW(hits.ljust(10))} {DIM('·')} {DIM(rel_time(mtime).ljust(8))} {DIM('·')} {DIM(proj)} {DIM('·')} {DIM(sid[:8])}"  # noqa: E501
        )
        if snip:
            print(f"      {DIM('…' + highlight(snip, keyword.split()) + '…')}")
        print(f"      {GREEN(resume_cmd(sid, cwd))}")
        print()


def index(n):
    files = sorted(
        (f for f in glob.glob(f"{ROOT}/*/*.jsonl") if is_session(f)), key=os.path.getmtime, reverse=True
    )[:n]
    print()
    for f in files:
        title, first, tickets = scan(f)
        sid = os.path.basename(f)[:-6]
        tk = "  ".join(sorted(tickets)[:8]) or DIM("—")
        print(f"  {BOLD(clean_label(title or first or '(empty)'))}")
        print(
            f"      {DIM(rel_time(os.path.getmtime(f)).ljust(8))} {DIM('·')} {DIM(proj_of(f))} {DIM('·')} {DIM(sid[:8])}"  # noqa: E501
        )
        print(f"      {DIM('tickets:')} {CYAN(tk)}")
        print()


# ── interactive browser (fzf) ────────────────────────────────────────────
def read_head(path, nbytes=65536):
    with open(path, "rb") as fh:
        return fh.read(nbytes).decode(errors="ignore")


def read_tail(path, nbytes=262144):
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        fh.seek(max(0, size - nbytes))
        data = fh.read().decode(errors="ignore")
    return data if size <= nbytes else data.split("\n", 1)[-1]


def session_cwd(path):
    """The directory `claude --resume` must run from — Claude Code scopes a session to the
    working dir it was launched in. Read the launch cwd from the transcript (each entry
    records its `cwd`; the first one is the launch dir). Fall back to decoding the encoded
    project-dir name (lossy on dir names containing '-') when no entry carries a cwd."""
    for ln in read_head(path).splitlines():
        try:
            cwd = json.loads(ln).get("cwd")
        except Exception:
            continue
        if cwd:
            return cwd
    name = os.path.basename(os.path.dirname(path))
    return "/" + name.lstrip("-").replace("-", "/") if name.startswith("-") else None


def resume_cmd(sid, cwd):
    """Shell command to resume a session: cd into its launch dir first, because
    `claude --resume` only finds sessions belonging to the current directory's project."""
    base = f"claude --resume {sid}"
    return f"cd {shlex.quote(cwd)} && {base}" if cwd else base


def meta_fast(path):
    """Title + first prompt + tickets without reading huge files in full."""
    head, tail = read_head(path), read_tail(path)
    title, first, tickets = None, None, set()
    for ln in tail.splitlines():
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") == "ai-title":
            title = o.get("aiTitle")
    for ln in head.splitlines():
        try:
            o = json.loads(ln)
        except Exception:
            continue
        if o.get("type") == "user":
            raw = o.get("message", {}).get("content")
            txt = (
                raw
                if isinstance(raw, str)
                else " ".join(p.get("text", "") for p in raw if isinstance(p, dict))
            )
            first = " ".join(txt.split())[:70]
            break
    tickets.update(TICKET.findall(head))
    tickets.update(TICKET.findall(tail))
    return title, first, tickets


def msg_text(o):
    """Natural-language text only — tool_use / tool_result parts are skipped."""
    raw = o.get("message", {}).get("content")
    if isinstance(raw, str):
        return raw
    parts = [
        p.get("text", "")
        for p in (raw if isinstance(raw, list) else [])
        if isinstance(p, dict) and (p.get("type") == "text" or "text" in p)
    ]
    return " ".join(s for s in parts if s)


def _wrap(tag_colored, tag_width, text, width, terms=None):
    """Print text with a colored role/label tag and a hanging indent that lines up under it."""
    indent = " " * (tag_width + 1)
    body = textwrap.fill(text, width=max(20, width), initial_indent=indent, subsequent_indent=indent)
    body = (tag_colored + " ") + body[len(indent) :]
    if terms:
        body = highlight(body, terms)
    print(body)


TAGS = {"you": MAGENTA("you  "), "cc": GREEN("cc   "), "think": DIM("think"), "title": CYAN("title")}
# stamp "MM-DD HH:MM" (11) + space + role (5) = 17
TAG_WIDTH = 17


def render_msg(role, ts, text, width, limit=None, terms=None):
    body = " ".join(text.split())
    if limit and len(body) > limit:
        body = body[:limit].rstrip() + " …"
    _wrap(f"{DIM(local_stamp(ts))} {TAGS[role]}", TAG_WIDTH, body, width, terms)
    print()


def preview_session(path, keyword=None):
    width = int(os.environ.get("FZF_PREVIEW_COLUMNS", 84))
    title, first, tickets = meta_fast(path)
    print(BOLD(clean_label(title or first or "(empty)")))
    print(
        DIM(f"{rel_time(os.path.getmtime(path))}  ·  {proj_of(path)}  ·  {os.path.basename(path)[:-6][:8]}")
    )
    if tickets:
        print(DIM("tickets  ") + CYAN("  ".join(sorted(tickets)[:10])))
    print()

    sid = os.path.basename(path)[:-6]
    if not os.path.exists(text_cache(sid)):
        build_cache(path, sid)
    entries = cache_entries(sid)

    if keyword:
        mode = get_mode()
        hl_terms = [keyword] if mode == "phrase" else keyword.split()  # phrase = one literal term
        ml = [t.lower() for t in hl_terms]
        if mode == "message" and len(ml) > 1:
            matches = [
                i for i, (role, txt, ts) in enumerate(entries) if all(t in txt.lower() for t in ml)
            ]  # all terms in one message
        else:
            matches = [
                i for i, (role, txt, ts) in enumerate(entries) if any(t in txt.lower() for t in ml)
            ]  # any term (or the phrase)
        total = len(matches)
        if not total:
            print(
                DIM(
                    f"“{keyword}” not shown ({mode} mode): the terms may be in tool output, "
                    "or — in session mode — only across separate messages."
                )
            )
            return
        matchset = set(matches)
        # Group selection: in session mode guarantee one message per term (so every AND term
        # is visible); otherwise just the earliest matches. Cap at 4 groups.
        groups, seen = [], set()
        if mode == "session" and len(ml) > 1:
            for term in ml:
                for i in matches:
                    if i not in seen and term in entries[i][1].lower():
                        groups.append(i)
                        seen.add(i)
                        break
        for i in matches:
            if len(groups) >= 4:
                break
            if i not in seen:
                groups.append(i)
                seen.add(i)
        groups.sort()
        print(YELLOW(f"▌ {total} match{'es' if total != 1 else ''} for “{keyword}” · {mode}"))
        print(DIM("─" * min(width, 60)))
        printed = set()
        for gi, mi in enumerate(groups):
            for j in (mi - 1, mi, mi + 1):
                if not (0 <= j < len(entries)) or j in printed:
                    continue
                printed.add(j)
                role, txt, ts = entries[j]
                if j in matchset:
                    render_msg(role, ts, txt, width, terms=hl_terms)  # matched: full + highlight
                else:
                    render_msg(role, ts, txt, width, limit=200)  # context before/after: collapsed
            if gi < len(groups) - 1:
                print(DIM("      ⋯"))
        if total > len(groups):
            print(DIM(f"      ⋯  +{total - len(groups)} more"))
        return

    print(DIM("─" * min(width, 60)))
    for role, txt, ts in entries[-14:]:
        render_msg(role, ts, txt, width, limit=400)


def short_proj(path):
    # Trim a leading workspace/monorepo prefix so the label is just the repo/dir name.
    # Extend for your own layout with CC_PROJ_STRIP="prefix1-|prefix2-" (longest-match wins).
    p = proj_of(path).replace("~/", "")
    prefixes = os.environ.get("CC_PROJ_STRIP", "code-|src-|repos-|dev-|projects-").split("|")
    for pre in sorted((x for x in prefixes if x), key=len, reverse=True):
        if p.startswith(pre):
            p = p[len(pre) :]
            break
    return p or "~"


def fzf_line(f, count=None):
    title, first, tickets = meta_fast(f)
    sid = os.path.basename(f)[:-6]
    ago = rel_time(os.path.getmtime(f))
    tk = " ".join(sorted(tickets)[:5])
    label = clean_label(title or first or "(empty)")
    cnt = f"{count}×" if count else ""
    # pad plain text first, then colorize, so columns line up (ANSI codes have zero display width)
    display = (
        f"{DIM(ago.ljust(7))}  {CYAN(cnt.ljust(6))}{DIM(short_proj(f).ljust(15))}  {BOLD(label)}  {DIM(tk)}"
    )
    return f"{display}\t{sid}\t{f}"


def recent_files(n):
    return sorted(
        (f for f in glob.glob(f"{ROOT}/*/*.jsonl") if is_session(f)), key=os.path.getmtime, reverse=True
    )[:n]


def search_lines(keyword, n=60):
    """Emit fzf candidate lines. Empty query → recent N; else → conversation matches ranked by count."""
    srcs = refresh_cache(verbose=False)
    if not keyword.strip():
        for f in sorted(srcs.values(), key=os.path.getmtime, reverse=True)[:n]:
            print(fzf_line(f))
        return
    counts = matching(keyword, get_mode(), srcs)
    rows = [(srcs[sid], counts[sid]) for sid in counts]
    if get_sort() == "date":
        rows.sort(key=lambda r: os.path.getmtime(r[0]), reverse=True)
    else:
        rows.sort(key=lambda r: (r[1], os.path.getmtime(r[0])), reverse=True)
    for f, c in rows:
        print(fzf_line(f, c))


def browse(n):
    if not os.path.isdir(ROOT):
        print(DIM(f"no Claude Code sessions found under {ROOT}  (set CLAUDE_CONFIG_DIR?)"))
        return
    if shutil.which("rg") is None:
        print(DIM("ripgrep (rg) not found — install it (macOS: brew install ripgrep)"))
        return
    if shutil.which("fzf") is None:
        print(DIM("fzf not found — falling back to --index. Install with: brew install fzf\n"))
        index(n)
        return
    set_mode("message")  # each launch starts in one-message mode, sorted by date
    set_sort("date")
    # fzf re-invokes ccsearch for its reload/preview/transform binds. Route those back through
    # the installed package (`python -m ccsearch`), not the source file — once installed as a
    # wheel the entry point lives in a venv and `python3 <cli.py>` would not resolve imports.
    me = f"{shlex.quote(sys.executable)} -m ccsearch"
    reload_cmd = f"{me} --search-lines {n} {{q}}"
    scheme = (
        "fg+:bright-white:bold,bg+:238,hl:cyan,hl+:bright-yellow,"
        "prompt:green,pointer:bright-magenta,marker:bright-magenta,info:dim,header:dim,"
        "border:240,separator:240,preview-border:240,scrollbar:240,"
        "preview-scrollbar:240,gutter:-1,label:cyan,preview-label:cyan,query:bright-white"
    )
    res = subprocess.run(
        [
            "fzf",
            "--ansi",
            "--disabled",
            "--delimiter",
            "\t",
            "--with-nth",
            "1",
            "--prompt",
            prompt_label(),
            "--pointer",
            "▌",
            "--marker",
            "▌",
            "--height",
            "100%",
            "--layout",
            "reverse",
            "--info",
            "inline-right",
            "--border",
            "rounded",
            "--border-label",
            " ccsearch ",
            "--padding",
            "0,1",
            "--color",
            scheme,
            "--header",
            "type to search · ^t mode (anywhere/one-msg/exact) · ^s sort (date/matches) · enter open · esc",
            "--bind",
            f"start:reload({reload_cmd})",
            "--bind",
            f"change:reload({reload_cmd})",
            "--bind",
            "ctrl-u:preview-half-page-up,ctrl-d:preview-half-page-down",
            "--bind",
            f"ctrl-t:transform-prompt({me} --cycle-mode)+reload({reload_cmd})+refresh-preview",
            "--bind",
            f"ctrl-s:transform-prompt({me} --toggle-sort)+reload({reload_cmd})",
            "--preview",
            f"{me} --preview {{3}} {{q}}",
            "--preview-window",
            "right,56%,wrap,border-left",
        ],
        capture_output=True,
        text=True,
    )
    if res.returncode != 0 or not res.stdout.strip():
        return
    fields = res.stdout.strip("\n").split("\t")  # fzf_line packs: display \t sid \t transcript-path
    sid = fields[1]
    cwd = session_cwd(fields[2]) if len(fields) > 2 else None
    print(GREEN(resume_cmd(sid, cwd)))
    try:
        # Claude Code scopes --resume to the current project dir, so enter the session's
        # launch dir first; otherwise resuming a session from another folder fails.
        if cwd and os.path.isdir(cwd):
            os.chdir(cwd)
        os.execvp("claude", ["claude", "--resume", sid])
    except OSError as e:
        print(DIM(f"couldn't launch claude ({e}) — run the command above manually."), file=sys.stderr)


def _int_arg(args, default):
    """Parse args[1] as a positive int; fall back to default on missing/invalid."""
    if len(args) > 1:
        try:
            return max(1, int(args[1]))
        except ValueError:
            print(DIM(f"expected a number, got '{args[1]}' — using {default}"), file=sys.stderr)
    return default


def main(argv=None):
    global _TTY
    args = sys.argv[1:] if argv is None else list(argv)
    # fzf pipes these two modes' stdout (not a TTY) but renders ANSI via --ansi / the
    # preview window — so force color on; isatty() would otherwise strip it.
    if args and args[0] in ("--preview", "--search-lines"):
        _TTY = os.environ.get("NO_COLOR") is None
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
    elif args and args[0] == "--index":
        index(_int_arg(args, 15))
    elif args and args[0] == "--preview":
        # --preview <path> [query words...]
        preview_session(args[1], " ".join(args[2:]) or None)
    elif args and args[0] == "--search-lines":
        # --search-lines <n> [query words...]
        search_lines(" ".join(args[2:]), _int_arg(args, 60))
    elif args and args[0] == "--cycle-mode":
        cycle_mode()
        print(prompt_label(), end="")  # for transform-prompt
    elif args and args[0] == "--toggle-sort":
        toggle_sort()
        print(prompt_label(), end="")  # for transform-prompt
    elif args and args[0] in ("-i", "--browse"):
        browse(_int_arg(args, 60))
    elif args:
        find(args[0])
    else:
        browse(60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
