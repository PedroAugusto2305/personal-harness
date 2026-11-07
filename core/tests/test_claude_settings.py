import json
import shlex
from pathlib import Path

from harness_core.claude_settings import HOOK_EVENTS, build_claude_settings, claude_argv

RELAY = Path("/Users/teste/Harness Home/bin/relay.sh")


def test_statusline_points_to_quoted_relay():
    command = build_claude_settings(RELAY)["statusLine"]["command"]
    assert shlex.split(command) == ["/bin/sh", str(RELAY), "statusline"]


def test_every_hook_event_calls_relay_with_its_name():
    hooks = build_claude_settings(RELAY)["hooks"]
    assert set(hooks) == set(HOOK_EVENTS)
    for event, entries in hooks.items():
        command = entries[0]["hooks"][0]["command"]
        assert shlex.split(command) == ["/bin/sh", str(RELAY), "hook", event]


def test_argv_passes_settings_as_one_json_argument():
    argv = claude_argv("/usr/local/bin/claude", RELAY)
    assert argv[:2] == ["/usr/local/bin/claude", "--settings"]
    assert json.loads(argv[2]) == build_claude_settings(RELAY)
