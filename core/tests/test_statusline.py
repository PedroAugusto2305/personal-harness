from harness_core.statusline import parse_statusline, render_statusline


def test_parse_reads_context_cost_and_limits(statusline_payload):
    parsed = parse_statusline(statusline_payload)
    assert parsed["model"] == "Opus 5.5"
    assert parsed["cwd"] == "/Users/teste/projeto"
    assert parsed["context"] == {"used_pct": 38.2, "size": 200000, "used_tokens": 76200}
    assert parsed["cost_usd"] == 0.42
    assert parsed["rate_limits"]["five_hour"] == {"used_pct": 23.5, "resets_at": 1794080000}
    assert parsed["rate_limits"]["seven_day"]["used_pct"] == 41.2


def test_missing_fields_become_none_not_zero():
    # Início de sessão: contexto ainda nulo e sem rate_limits.
    parsed = parse_statusline({"model": {"display_name": "Sonnet 5.5"}, "context_window": {"used_percentage": None}})
    assert parsed["context"] == {"used_pct": None, "size": None, "used_tokens": None}
    assert parsed["rate_limits"] == {}
    assert parsed["cost_usd"] is None


def test_partial_rate_limits_keep_only_present_windows():
    parsed = parse_statusline({"rate_limits": {"seven_day": {"used_percentage": 84}}})
    assert list(parsed["rate_limits"]) == ["seven_day"]


def test_render_is_short(statusline_payload):
    assert render_statusline(parse_statusline(statusline_payload)) == "◆ metis · Opus 5.5 · contexto 38%"
    assert render_statusline(parse_statusline({})) == "◆ metis"
