"""도구 수준 테스트(판정_명세.md 7절 T21·T22)."""

import logging

import pytest

from common import cache
from common.errors import FetchError, ToolError
from common.models import NoticeDetail
from mjc_connector import tool
from mjc_connector.eligibility import Extraction, Profile

BODY = "대상: 전 학과 2학년 재학생. 신청기간: 2026.10.15 ~ 2099.10.31."
PROFILE = Profile(department="정보통신공학과", grade=2, status="재학")
EXTRACTION = Extraction.model_validate(
    {
        "grades": {"value": [2], "quote": "2학년"},
        "departments": {"value": "ANY", "quote": "전 학과"},
        "statuses": {"value": ["재학"], "quote": "재학생"},
        "apply_end": {"value": "2099-10-31", "quote": "2099.10.31"},
    }
)


def _detail() -> NoticeDetail:
    return NoticeDetail(
        title="시험 공지",
        department="학사지원팀",
        posted_on="2026-10-10",
        views=1,
        body=BODY,
        attachments=[],
        truncated=False,
    )


def test_tool_fetches_body_itself_and_judges(monkeypatch):
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    v = tool.evaluate_eligibility("169:BM1:BD1", PROFILE, EXTRACTION)
    assert v.verdict == "가능"
    assert v.deadline is not None


def test_t22_fetch_failure_is_an_error_not_a_verdict(monkeypatch):
    def fail(notice_id):
        raise FetchError("시험")

    monkeypatch.setattr(tool.notices, "get_notice", fail)
    with pytest.raises(ToolError):
        tool.evaluate_eligibility("169:BM1:BD1", PROFILE, EXTRACTION)


def test_t21_profile_is_not_left_in_logs_or_cache(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    secret = Profile(department="컴퓨터보안공학과", grade=3, status="휴학")
    with caplog.at_level(logging.DEBUG):
        tool.evaluate_eligibility("169:BM1:BD1", secret, EXTRACTION)
    # 학년(3)은 숫자라 다른 로그와 구분되지 않아 학과·재학 상태로 확인한다.
    # get_notice를 대신했으므로 캐시 쪽은 이 도구가 새로 쓰는 파일이 없는지만 본다.
    for value in ("컴퓨터보안공학과", "휴학"):
        assert value not in caplog.text
    assert list(tmp_path.glob("*")) == []


def _call_through_mcp(monkeypatch, arguments: dict):
    """MCP 클라이언트로 도구를 불러 SDK의 인자 검증까지 거친 결과를 돌려준다."""
    import asyncio

    from mcp.client import Client
    from mcp.server import MCPServer

    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    server = MCPServer("test")
    tool.register(server)

    async def call():
        async with Client(server) as client:
            return await client.call_tool("evaluate_eligibility", arguments)

    return asyncio.run(call())


_ID = "169:BM1:BD1"


@pytest.mark.parametrize(
    ("arguments", "secret"),
    [
        ({"notice_id": _ID, "profile": {"department": "정보통신공학과", "grade": 9, "status": "재학"}, "extraction": {}}, "input_value"),
        ({"notice_id": _ID, "profile": {"department": "정보통신공학과", "grade": 2, "status": "비밀상태"}, "extraction": {}}, "비밀상태"),
        ({"notice_id": _ID, "profile": {"department": "비밀학과", "grade": 2}, "extraction": {}}, "비밀학과"),
        ({"notice_id": _ID, "profile": "비밀학과", "extraction": {}}, "비밀학과"),
        ({"notice_id": _ID, "profile": ["비밀학과"], "extraction": {}}, "비밀학과"),
        ({"notice_id": _ID, "profile": {"department": "비밀학과", "grade": 3, "status": "휴학"}}, "비밀학과"),
        ({"notice_id": _ID, "profile": {"department": "비밀학과", "grade": 2, "status": "재학"}, "extraction": {}}, "비밀학과"),
    ],
)
def test_invalid_arguments_through_mcp_are_tool_errors_without_input_values(monkeypatch, arguments, secret):
    """SDK 인자 검증에서 걸린 값도 도구가 입력값 없는 ToolError로 바꾼다(명세 1절 입력 형태, T21)."""
    result = _call_through_mcp(monkeypatch, arguments)
    text = result.content[0].text
    assert result.is_error
    assert "올바르지 않습니다" in text or "정식 학과명" in text
    assert secret not in text


def test_profile_schema_is_still_generated_from_the_model():
    import asyncio

    from mcp.client import Client
    from mcp.server import MCPServer

    server = MCPServer("test")
    tool.register(server)

    async def schema():
        async with Client(server) as client:
            tools = (await client.list_tools()).tools
            return next(t for t in tools if t.name == "evaluate_eligibility").input_schema

    props = asyncio.run(schema())
    profile = props["properties"]["profile"]
    if "$ref" in profile:
        profile = props["$defs"][profile["$ref"].split("/")[-1]]
    assert set(profile["properties"]) == {"department", "grade", "status"}
    assert profile["properties"]["grade"]["maximum"] == 4


def test_unknown_department_in_tool_is_an_error(monkeypatch):
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    with pytest.raises(ToolError):
        tool.evaluate_eligibility(
            "169:BM1:BD1", Profile(department="정통과", grade=2, status="재학"), EXTRACTION
        )
