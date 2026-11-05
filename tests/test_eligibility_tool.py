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
    assert "컴퓨터보안공학과" not in caplog.text
    cached = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*"))
    assert "컴퓨터보안공학과" not in cached


def test_unknown_department_in_tool_is_an_error(monkeypatch):
    monkeypatch.setattr(tool.notices, "get_notice", lambda notice_id: _detail())
    with pytest.raises(ToolError):
        tool.evaluate_eligibility(
            "169:BM1:BD1", Profile(department="정통과", grade=2, status="재학"), EXTRACTION
        )
