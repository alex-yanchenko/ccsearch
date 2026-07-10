import json

from ccsearch import cli


def test_iter_entries_extracts_conversation_only():
    lines = [
        json.dumps({"type": "user", "timestamp": "t1", "message": {"content": "hello world"}}),
        json.dumps({"type": "user", "timestamp": "t2", "message": {"content": "<channel>machinery"}}),
        json.dumps(
            {
                "type": "user",
                "timestamp": "t3",
                "message": {"content": [{"type": "text", "text": "from list"}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "t4",
                "message": {"content": [{"type": "text", "text": "hi there"}]},
            }
        ),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": "t5",
                "message": {"content": [{"type": "thinking", "thinking": "pondering"}]},
            }
        ),
        json.dumps({"type": "summary", "summary": "ignored"}),
        "not valid json",
    ]

    assert list(cli.iter_entries(lines)) == [
        ("you", "t1", "hello world"),
        ("you", "t3", "from list"),
        ("cc", "t4", "hi there"),
        ("think", "t5", "pondering"),
    ]


def test_clean_label_channel_command_and_passthrough():
    assert (
        cli.clean_label('<channel source="github-watcher" event_type="review_requested">')
        == "⟨github-watcher · review_requested⟩"
    )
    assert cli.clean_label('<channel source="pr-comment-watcher">') == "⟨pr-comment-watcher⟩"
    assert cli.clean_label("<command-name>/vet extra words") == "/vet"
    assert cli.clean_label("a plain session title") == "a plain session title"


def test_clean_snip_unescapes_collapses_and_trims():
    assert cli.clean_snip("foo\\nbar") == "foo bar"
    assert cli.clean_snip('"quoted",') == "quoted"
    assert cli.clean_snip("  a\\tb   c  ") == "a b c"


def test_sanitize_strips_terminal_control_chars_keeps_printables():
    assert cli._sanitize("x\x00\x1b\x07\x7f\x9fy") == "xy"
    assert cli._sanitize("plain café 日本 ✓") == "plain café 日本 ✓"


def test_clean_label_strips_escape_sequences():
    # ESC (\x1b) is removed so the sequence can't reach the terminal; the harmless residue stays.
    assert cli.clean_label("ti\x1b[2Jtle") == "ti[2Jtle"
    assert cli.clean_label("normal title") == "normal title"


def test_clean_snip_strips_control_chars():
    assert cli.clean_snip("a\x1bb\x07c") == "abc"


def test_int_arg_parses_and_falls_back():
    assert cli._int_arg(["--index"], 15) == 15
    assert cli._int_arg(["--index", "5"], 15) == 5
    assert cli._int_arg(["--index", "-3"], 15) == 1
    assert cli._int_arg(["--index", "abc"], 15) == 15


def test_main_help_prints_usage_and_returns_zero(capsys):
    rc = cli.main(["--help"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "search your Claude Code sessions" in out


def test_session_cwd_reads_launch_cwd_from_transcript(tmp_path):
    proj = tmp_path / "-Users-me-code-thing"
    proj.mkdir()
    transcript = proj / "sid.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "summary", "summary": "no cwd here"}),
                json.dumps({"type": "user", "cwd": "/Users/me/code/thing", "message": {"content": "hi"}}),
                json.dumps({"type": "assistant", "cwd": "/Users/me/elsewhere", "message": {"content": []}}),
            ]
        )
    )
    assert cli.session_cwd(str(transcript)) == "/Users/me/code/thing"


def test_session_cwd_falls_back_to_decoded_project_dir(tmp_path):
    proj = tmp_path / "-Users-me-code-thing"
    proj.mkdir()
    transcript = proj / "sid.jsonl"
    transcript.write_text(json.dumps({"type": "summary", "summary": "no cwd anywhere"}))
    assert cli.session_cwd(str(transcript)) == "/Users/me/code/thing"
