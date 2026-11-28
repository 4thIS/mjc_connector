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


def test_t40_tool_marks_attachments_as_not_read(monkeypatch):
    detail = _detail().model_copy(update={"attachments": ["신청서.hwp"]})
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: detail)
    v = tool.evaluate_eligibility("169:BM1:BD1", PROFILE, EXTRACTION)
    assert v.attachment_status == "not_read"
    assert "첨부" in v.answer_guide
    # 대상이 비어 있으면 첨부 때문에 추정하지 않아야 한다(도구가 첨부 여부를 넘기는지 확인)
    empty = Extraction.model_validate({"organizer": "school", "apply_end": EXTRACTION.apply_end.model_dump()})
    v = tool.evaluate_eligibility("169:BM1:BD1", PROFILE, empty)
    assert v.verdict == "확인 필요"
    for reason in v.reasons:
        if reason.field in ("grades", "departments", "statuses"):
            assert (reason.result, reason.source) == ("unknown", "missing")
            assert "첨부" in reason.evidence


@pytest.mark.parametrize("update", [{"truncated": True}, {"body_images": ["https://mjcms.mjc.ac.kr/a.png"]}])
def test_t46_t47_tool_passes_truncation_and_images(monkeypatch, update):
    detail = _detail().model_copy(update=update)
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: detail)
    extraction = EXTRACTION.model_copy(update={"grades": EXTRACTION.grades.model_copy(update={"value": None, "quote": None})})
    v = tool.evaluate_eligibility("169:BM1:BD1", PROFILE, extraction)
    assert v.verdict == "확인 필요"


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


@pytest.mark.parametrize("field", ["grades", "departments", "statuses"])
def test_t29_empty_list_through_mcp_is_a_tool_error(monkeypatch, field):
    result = _call_through_mcp(
        monkeypatch,
        {"notice_id": _ID, "profile": {"department": "비밀학과", "grade": 2, "status": "재학"},
         "extraction": {field: {"value": [], "quote": "비밀인용"}}},
    )
    text = result.content[0].text
    assert result.is_error
    assert f"extraction.{field}.value" in text
    assert "비밀학과" not in text and "비밀인용" not in text


# ---- mj-08 보강: 명세 1절(서버가 본문·작성일·KST 오늘을 정함)과 T21·T22의 빠진 경우 ----

from datetime import date, datetime, timezone

from common.errors import ParseError

SECRET = Profile(department="컴퓨터보안공학과", grade=3, status="휴학")


def test_tool_fetches_the_notice_it_was_given(monkeypatch):
    """본문은 호출받은 notice_id로 서버가 직접 가져온다(1절)."""
    asked = []

    def fake(notice_id):
        asked.append(notice_id)
        return _detail()

    monkeypatch.setattr(tool.notices, "get_notice", fake)
    tool.evaluate_eligibility("169:BM1:BD7", PROFILE, EXTRACTION)
    assert asked == ["169:BM1:BD7"]


@pytest.mark.parametrize("error", [FetchError("시험"), ParseError("공지 본문"), ParseError("공지 식별자 형식")])
def test_t22_every_notice_error_is_raised_not_judged(monkeypatch, error):
    """조회 단계의 ToolError 계열은 종류와 관계없이 판정 대신 오류로 나온다(5절)."""

    def fail(notice_id):
        raise error

    monkeypatch.setattr(tool.notices, "get_notice", fail)
    with pytest.raises(ToolError):
        tool.evaluate_eligibility("169:BM1:BD1", PROFILE, EXTRACTION)


def test_t21_t22_fetch_error_message_and_logs_do_not_hold_profile(monkeypatch, caplog):
    """조회가 실패한 경로에서도 오류 메시지와 로그에 프로필이 남지 않는다."""

    def fail(notice_id):
        raise FetchError("시험")

    monkeypatch.setattr(tool.notices, "get_notice", fail)
    with caplog.at_level(logging.DEBUG), pytest.raises(ToolError) as info:
        tool.evaluate_eligibility("169:BM1:BD1", SECRET, EXTRACTION)
    for value in ("컴퓨터보안공학과", "휴학"):
        assert value not in str(info.value)
        assert value not in caplog.text


def test_t21_t22_fetch_error_through_mcp_does_not_hold_profile(monkeypatch):
    """MCP로 불렀을 때 조회 실패 결과도 오류이고, 그 문구에 프로필이 없다."""
    import asyncio

    from mcp.client import Client
    from mcp.server import MCPServer

    def fail(notice_id):
        raise FetchError("시험")

    monkeypatch.setattr(tool.notices, "get_notice", fail)
    server = MCPServer("test")
    tool.register(server)

    async def call():
        async with Client(server) as client:
            return await client.call_tool(
                "evaluate_eligibility",
                {"notice_id": _ID, "profile": SECRET.model_dump(), "extraction": EXTRACTION.model_dump()},
            )

    result = asyncio.run(call())
    text = result.content[0].text
    assert result.is_error
    assert "컴퓨터보안공학과" not in text and "휴학" not in text


def _freeze_now(monkeypatch, utc: datetime):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return utc.astimezone(tz)

    monkeypatch.setattr(tool, "datetime", Frozen)


@pytest.mark.parametrize(
    ("utc", "verdict"),
    [
        (datetime(2026, 10, 31, 14, 59, tzinfo=timezone.utc), "가능"),  # KST 10/31 23:59, 마감 당일
        (datetime(2026, 10, 31, 15, 0, tzinfo=timezone.utc), "불가"),  # KST 11/01 00:00, 마감 지남
    ],
)
def test_today_is_kst_date(monkeypatch, utc, verdict):
    """오늘 날짜는 서버가 KST로 정한다(1절). UTC로 정하면 마감 다음 날 0~9시를 당일로 본다."""
    body = BODY.replace("2099.10.31", "2026.10.31")
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail().model_copy(update={"body": body}))
    _freeze_now(monkeypatch, utc)
    extraction = EXTRACTION.model_copy(
        update={"apply_end": EXTRACTION.apply_end.model_copy(update={"value": date(2026, 10, 31), "quote": "2026.10.31"})}
    )
    assert tool.evaluate_eligibility(_ID, PROFILE, extraction).verdict == verdict


@pytest.mark.parametrize("posted_on", ["", "작성일 없음"])
def test_unreadable_posted_on_still_judges(monkeypatch, posted_on):
    """작성일을 날짜로 읽지 못해도 판정은 그대로 한다(posted_on은 선택 인자, 1절)."""
    monkeypatch.setattr(
        tool.notices, "get_notice", lambda notice_id: _detail().model_copy(update={"posted_on": posted_on})
    )
    assert tool.evaluate_eligibility(_ID, PROFILE, EXTRACTION).verdict == "가능"
