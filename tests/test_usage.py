"""시험 운영 기록 테스트: 정해 둔 칸만 적고 입력값은 남기지 않는다."""

import json

import pytest
from common.errors import ToolError
from mcp.server import MCPServer

from mjc_connector import usage


def _server():
    mcp = MCPServer("t")

    @mcp.tool()
    def search_notices(category: str = "academic", keyword: str | None = None) -> str:
        return "ok"

    @mcp.tool()
    def broken(notice_id: str) -> str:
        raise ToolError("조회 실패")

    usage.instrument(mcp)
    return mcp


def _call(mcp, name, **kwargs):
    return mcp._tool_manager.get_tool(name).fn(**kwargs)


def test_records_only_allowed_fields(monkeypatch, tmp_path):
    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("MJC_USAGE_LOG", str(log))
    mcp = _server()
    _call(mcp, "search_notices", category="scholarship", keyword="비밀검색어")
    with pytest.raises(ToolError):
        _call(mcp, "broken", notice_id="169:BM1:BD99")
    text = log.read_text(encoding="utf-8")
    assert "비밀검색어" not in text and "scholarship" not in text and "BD99" not in text
    first, second = [json.loads(line) for line in text.splitlines()]
    assert set(first) == {"ts", "tool", "ok", "ms"} and first["tool"] == "search_notices" and first["ok"]
    assert set(second) == {"ts", "tool", "ok", "error", "ms"} and second["error"] == "ToolError"


def test_eligibility_records_verdict_but_not_profile(monkeypatch, tmp_path):
    from mjc_connector import tool
    from mjc_connector.eligibility import Profile
    from tests.test_eligibility_tool import EXTRACTION, _detail

    log = tmp_path / "usage.jsonl"
    monkeypatch.setenv("MJC_USAGE_LOG", str(log))
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    mcp = MCPServer("t")
    tool.register(mcp)
    usage.instrument(mcp)
    secret = Profile(department="컴퓨터보안공학과", grade=3, status="휴학")
    _call(mcp, "evaluate_eligibility", notice_id="169:BM1:BD1", profile=secret, extraction=EXTRACTION)
    text = log.read_text(encoding="utf-8")
    assert "컴퓨터보안공학과" not in text and "휴학" not in text
    entry = json.loads(text)
    assert set(entry) == {"ts", "tool", "ok", "ms", "verdict", "confidence"}


def test_disabled_without_path_and_failures_do_not_break_tools(monkeypatch, tmp_path):
    monkeypatch.delenv("MJC_USAGE_LOG", raising=False)
    assert _call(_server(), "search_notices") == "ok"
    monkeypatch.setenv("MJC_USAGE_LOG", str(tmp_path / "no-such-dir" / "usage.jsonl"))
    assert _call(_server(), "search_notices") == "ok"
