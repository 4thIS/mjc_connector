"""판정 함수 테스트. 케이스 번호는 docs/판정_명세.md 7절 표의 번호다.

날짜 교차 검증(T05b, T16 계열)은 별도 작업이라 여기에 없다.
"""

from datetime import date

import pytest

from common.errors import ToolError
from mjc_connector.eligibility import Extraction, evaluate, parse_profile

TODAY = date(2026, 10, 20)
BODY = "대상: 전 학과 2학년 재학생. 신청기간: 2026.10.15 ~ 2026.10.31. 접수 방법은 학과 사무실 방문."
PROFILE = {"department": "정보통신공학과", "grade": 2, "status": "재학"}


def _extraction(**override) -> Extraction:
    """기본은 모든 필드가 본문 인용으로 일치한다."""
    fields = {
        "grades": {"value": [2], "quote": "2학년"},
        "departments": {"value": "ANY", "quote": "전 학과"},
        "statuses": {"value": ["재학"], "quote": "재학생"},
        "apply_start": {"value": "2026-10-15", "quote": "2026.10.15"},
        "apply_end": {"value": "2026-10-31", "quote": "2026.10.31"},
    }
    fields.update(override)
    return Extraction.model_validate(fields)


def _run(extraction=None, body=BODY, profile=PROFILE, today=TODAY):
    return evaluate(parse_profile(profile), extraction or _extraction(), body, today)


def _reason(verdict, field):
    return next(r for r in verdict.reasons if r.field == field)


def test_t01_all_text_quotes_match():
    v = _run()
    assert v.verdict == "가능"
    assert v.confidence == "verified"
    assert v.deadline.date == date(2026, 10, 31)
    assert v.deadline.d_day == 11


def test_t02_grade_mismatch_is_rejected():
    body = BODY.replace("2학년", "3학년")
    v = _run(_extraction(grades={"value": [3], "quote": "3학년"}), body=body)
    assert v.verdict == "불가"
    assert _reason(v, "grades").result == "mismatch"


def test_t03_deadline_passed():
    body = BODY.replace("2026.10.31", "2026.10.19")
    v = _run(_extraction(apply_end={"value": "2026-10-19", "quote": "2026.10.19"}), body=body)
    assert v.verdict == "불가"
    assert _reason(v, "apply_end").result == "mismatch"


def test_t04_deadline_today_is_included():
    body = BODY.replace("2026.10.31", "2026.10.20")
    v = _run(_extraction(apply_end={"value": "2026-10-20", "quote": "2026.10.20"}), body=body)
    assert v.verdict == "가능"
    assert v.deadline.d_day == 0


def test_t05_not_yet_open_does_not_change_verdict():
    body = BODY.replace("2026.10.15", "2026.10.25")
    v = _run(_extraction(apply_start={"value": "2026-10-25", "quote": "2026.10.25"}), body=body)
    assert v.verdict == "가능"
    assert _reason(v, "apply_start").result == "not_yet"


def test_t05b_unverifiable_start_date_is_ignored_in_verdict():
    """apply_start 인용에 그 날짜가 없으면 unknown이지만 판정에는 쓰지 않는다."""
    v = _run(_extraction(apply_start={"value": "2026-10-16", "quote": "2026.10.15"}))
    assert v.verdict == "가능"
    r = _reason(v, "apply_start")
    assert (r.result, r.source) == ("unknown", "unverified_quote")
    assert v.confidence == "verified"


def test_t16c_deadline_quote_without_that_date_is_not_trusted():
    """B 방식: 인용(본문에 있음)에 값의 월·일이 없으면 날짜를 믿지 않는다."""
    v = _run(_extraction(apply_end={"value": "2026-11-06", "quote": "2026.10.31"}))
    assert v.verdict == "확인 필요"
    r = _reason(v, "apply_end")
    assert (r.result, r.source) == ("unknown", "unverified_quote")
    assert v.deadline is None


@pytest.mark.parametrize(
    ("body_date", "value"),
    [
        ("2026.10.31", "2026-10-31"),
        ("10월 31일", "2026-10-31"),
        ("10/31", "2026-10-31"),
        ("2026-10-31", "2026-10-31"),
        ("26.10.31.(금) 18시", "2026-10-31"),
        ("11. 6.(금)", "2026-11-06"),
        ("11월 06일", "2026-11-06"),
    ],
)
def test_t16c_accepts_common_korean_date_formats(body_date, value):
    body = BODY.replace("2026.10.31", body_date)
    v = _run(_extraction(apply_end={"value": value, "quote": body_date}), body=body, today=date(2026, 10, 1))
    assert _reason(v, "apply_end").source == "text_quote"


def test_t16c_does_not_match_day_inside_a_longer_number():
    """10/3을 찾을 때 10.31을 일치로 보지 않는다."""
    v = _run(_extraction(apply_end={"value": "2026-10-03", "quote": "2026.10.31"}), today=date(2026, 10, 1))
    assert _reason(v, "apply_end").source == "unverified_quote"


def test_t16c_image_dates_are_not_cross_checked():
    v = _run(_extraction(apply_end={"value": "2026-11-06", "from_image": True}))
    assert _reason(v, "apply_end").source == "image_read"


def test_t06_status_mismatch_is_rejected():
    body = BODY.replace("재학생", "휴학생")
    v = _run(_extraction(statuses={"value": ["휴학"], "quote": "휴학생"}), body=body)
    assert v.verdict == "불가"


def test_t07_image_mismatch_is_lowered_to_check_needed():
    v = _run(_extraction(departments={"value": ["경영학과"], "from_image": True}))
    assert v.verdict == "확인 필요"
    assert v.confidence == "image_unverified"
    assert "원본" in _reason(v, "departments").evidence


def test_t08_all_from_image_match():
    fields = {
        name: {"value": spec, "from_image": True}
        for name, spec in {
            "grades": [2],
            "departments": ["정보통신공학과"],
            "statuses": ["재학"],
            "apply_start": "2026-10-15",
            "apply_end": "2026-10-31",
        }.items()
    }
    v = _run(Extraction.model_validate(fields))
    assert v.verdict == "가능"
    assert v.confidence == "image_unverified"


def test_t09_text_mismatch_wins_over_image_mismatch():
    body = BODY.replace("2학년", "3학년")
    v = _run(
        _extraction(
            grades={"value": [3], "quote": "3학년"},
            departments={"value": ["경영학과"], "from_image": True},
        ),
        body=body,
    )
    assert v.verdict == "불가"


def test_t10_text_match_with_image_mismatch_is_check_needed():
    v = _run(_extraction(departments={"value": ["경영학과"], "from_image": True}))
    assert v.verdict == "확인 필요"


def test_t11_quote_not_in_body_is_not_trusted():
    v = _run(_extraction(grades={"value": [2], "quote": "2학년 이상 누구나"}))
    assert v.verdict == "확인 필요"
    r = _reason(v, "grades")
    assert (r.result, r.source) == ("unknown", "unverified_quote")
    assert v.confidence == "partial"


def test_t12_quote_whitespace_differences_are_ignored():
    v = _run(_extraction(apply_end={"value": "2026-10-31", "quote": "2026.10.15  ~\n2026.10.31"}))
    assert v.verdict == "가능"


def test_t13_missing_deadline_is_check_needed():
    v = _run(_extraction(apply_end={"value": None}))
    assert v.verdict == "확인 필요"
    assert _reason(v, "apply_end").source == "missing"
    assert v.deadline is None


def test_t14_all_fields_missing_is_check_needed():
    v = _run(Extraction())
    assert v.verdict == "확인 필요"


def test_t15_any_without_quote_is_not_trusted():
    v = _run(_extraction(departments={"value": "ANY"}))
    assert v.verdict == "확인 필요"
    assert _reason(v, "departments").source == "unverified_quote"
    assert v.confidence == "partial"


def test_t15b_any_with_quote_in_body_matches():
    v = _run(_extraction(departments={"value": "ANY", "quote": "전 학과"}))
    assert v.verdict == "가능"
    assert v.confidence == "verified"


def test_t17_value_without_any_evidence_is_not_trusted():
    v = _run(_extraction(grades={"value": [2]}))
    assert v.verdict == "확인 필요"
    assert _reason(v, "grades").source == "unverified_quote"


def test_t18_unknown_profile_department_is_an_error():
    with pytest.raises(ToolError):
        parse_profile({**PROFILE, "department": "정통과"})


def test_t19_missing_profile_field_is_an_error():
    with pytest.raises(ToolError):
        parse_profile({"department": "정보통신공학과", "grade": 2})


def test_t20_same_input_same_result():
    assert _run() == _run()


def test_t23_unrecognized_status_value_is_not_used():
    v = _run(_extraction(statuses={"value": ["복학생"], "quote": "재학생"}))
    assert v.verdict == "확인 필요"
    r = _reason(v, "statuses")
    assert (r.result, r.source) == ("unknown", "unrecognized_value")


@pytest.mark.parametrize("status", ["복학", "", "enrolled"])
def test_t24_profile_status_outside_allowed_values_is_an_error(status):
    with pytest.raises(ToolError):
        parse_profile({**PROFILE, "status": status})


@pytest.mark.parametrize("grade", [0, 5])
def test_t25_profile_grade_out_of_range_is_an_error(grade):
    with pytest.raises(ToolError):
        parse_profile({**PROFILE, "grade": grade})


def test_t26_unrecognized_department_value_is_not_used():
    v = _run(_extraction(departments={"value": ["정통과"], "quote": "전 학과"}))
    assert v.verdict == "확인 필요"
    r = _reason(v, "departments")
    assert (r.result, r.source) == ("unknown", "unrecognized_value")


def test_errors_do_not_echo_profile_values():
    """오류 문구에 학생이 입력한 값을 되풀이하지 않는다(개인정보 비저장 방침)."""
    with pytest.raises(ToolError) as info:
        parse_profile({**PROFILE, "department": "비밀학과"})
    assert "비밀학과" not in str(info.value)
