"""빠진 대상의 해석(규칙 1·2)과 판정 범위 밖 조건 테스트. 케이스 번호는 docs/판정_명세.md 7절 T30~."""

from datetime import date

from mjc_connector.eligibility import Extraction, evaluate, parse_profile

TODAY = date(2026, 11, 6)
# 실제 공지(Comm-on 특강)처럼 대상 문구 없이 마감일만 있는 본문
BODY = "신청 마감일(11월 11일 17:00)까지 신청해 주세요."
PROFILE = {"department": "정보통신공학과", "grade": 2, "status": "재학"}
END = {"value": "2026-11-11", "quote": "신청 마감일(11월 11일 17:00)"}


def _run(fields: dict, body=BODY, profile=PROFILE, today=TODAY):
    return evaluate(parse_profile(profile), Extraction.model_validate(fields), body, today)


def _reason(verdict, field):
    return next(r for r in verdict.reasons if r.field == field)


def test_t30_school_notice_without_any_target_is_possible_by_assumption():
    v = _run({"organizer": "school", "apply_end": END})
    assert v.verdict == "가능"
    assert v.confidence == "assumed"
    for field in ("grades", "departments", "statuses"):
        r = _reason(v, field)
        assert (r.result, r.source) == ("match", "assumed")
        assert "적혀 있지 않아" in r.evidence
    assert v.deadline.d_day == 5


def test_t31_missing_status_is_not_assumed_without_school_organizer():
    for organizer in ("external", None):
        v = _run({"organizer": organizer, "apply_end": END})
        assert v.verdict == "확인 필요"
        assert (_reason(v, "statuses").result, _reason(v, "statuses").source) == ("unknown", "missing")


def test_t32_assumed_status_mismatch_is_not_rejected():
    v = _run({"organizer": "school", "apply_end": END}, profile={**PROFILE, "status": "휴학"})
    assert v.verdict == "확인 필요"
    r = _reason(v, "statuses")
    assert (r.result, r.source) == ("mismatch", "assumed")


def test_t33_stated_target_still_wins_over_assumption():
    body = "대상: 3학년 재학생. " + BODY
    v = _run(
        {"organizer": "school", "grades": {"value": [3], "quote": "3학년"}, "apply_end": END},
        body=body,
    )
    assert v.verdict == "불가"
    assert _reason(v, "departments").source == "assumed"


def test_t34_unverified_target_is_not_replaced_by_assumption():
    v = _run({"organizer": "school", "grades": {"value": [2], "quote": "본문에 없는 문장"}, "apply_end": END})
    assert v.verdict == "확인 필요"
    assert _reason(v, "grades").source == "unverified_quote"


def test_t35_missing_deadline_is_still_check_needed():
    v = _run({"organizer": "school"})
    assert v.verdict == "확인 필요"
    assert _reason(v, "apply_end").source == "missing"


def test_t36_other_conditions_turn_possible_into_check_needed():
    body = "전국 초등학교 5학년~대학생 30명(2003년~2015년생). " + BODY
    v = _run(
        {
            "organizer": "school",
            "apply_end": END,
            "other_conditions": [{"text": "2003년~2015년생", "quote": "2003년~2015년생"}],
        },
        body=body,
    )
    assert v.verdict == "확인 필요"
    (c,) = v.other_conditions
    assert (c.text, c.source, c.evidence) == ("2003년~2015년생", "text_quote", "2003년~2015년생")


def test_t37_other_conditions_do_not_soften_a_rejection():
    body = "만 39세 이하. 신청 마감일(11월 5일 17:00)"
    v = _run(
        {
            "organizer": "school",
            "apply_end": {"value": "2026-11-05", "quote": "신청 마감일(11월 5일 17:00)"},
            "other_conditions": [{"text": "만 39세 이하", "quote": "만 39세 이하"}],
        },
        body=body,
    )
    assert v.verdict == "불가"
    assert len(v.other_conditions) == 1


def test_t38_other_condition_evidence_is_checked_like_other_fields():
    v = _run(
        {
            "organizer": "school",
            "apply_end": END,
            "other_conditions": [
                {"text": "미혼", "from_image": True},
                {"text": "소득 8분위 이하", "quote": "본문에 없는 문장"},
                {"text": "차상위계층"},
            ],
        }
    )
    assert v.verdict == "확인 필요"
    assert [c.source for c in v.other_conditions] == ["image_read", "unverified_quote", "unverified_quote"]


def test_t39_no_other_conditions_by_default():
    v = _run({"organizer": "school", "apply_end": END})
    assert v.other_conditions == []


# 첨부·참조 공지가 있으면 대상을 추정하지 않는다(명세 3절 11번)


def test_t40_unread_attachments_block_assumption():
    v = evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate({"organizer": "school", "apply_end": END}),
        BODY,
        TODAY,
        has_attachments=True,
    )
    assert v.verdict == "확인 필요"
    assert v.attachment_status == "not_read"
    for field in ("grades", "departments", "statuses"):
        r = _reason(v, field)
        assert (r.result, r.source) == ("unknown", "missing")
        assert "첨부" in r.evidence


def test_t41_reference_to_other_notice_blocks_assumption():
    body = "대상·선발기준은 '교외 국가근로장학생 선발 안내'를 따릅니다. " + BODY
    v = _run(
        {
            "organizer": "school",
            "apply_end": END,
            "refers_elsewhere": {"quote": "대상·선발기준은 '교외 국가근로장학생 선발 안내'를 따릅니다."},
        },
        body=body,
    )
    assert v.verdict == "확인 필요"
    assert "다른 곳" in _reason(v, "grades").evidence


def test_t42_attachments_do_not_affect_stated_targets():
    body = "대상: 전 학년 전 학과 재학생. " + BODY
    v = evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate(
            {
                "grades": {"value": "ANY", "quote": "전 학년"},
                "departments": {"value": "ANY", "quote": "전 학과"},
                "statuses": {"value": ["재학"], "quote": "재학생"},
                "apply_end": END,
            }
        ),
        body,
        TODAY,
        has_attachments=True,
    )
    assert v.verdict == "가능"
    assert v.attachment_status == "not_read"


def test_t43_no_attachments_by_default():
    assert _run({"organizer": "school", "apply_end": END}).attachment_status == "none"


def test_t44_answer_guide_matches_verdict_level():
    possible = _run({"organizer": "school", "apply_end": END})
    assert "추정" in possible.answer_guide
    check = _run({"apply_end": END})
    assert check.verdict == "확인 필요"
    assert "가능을 암시" in check.answer_guide
    body = "대상: 3학년. " + BODY
    rejected = _run({"grades": {"value": [3], "quote": "3학년"}, "apply_end": END}, body=body)
    assert "사유" in rejected.answer_guide


# 대상이 근거·잘린 본문·이미지에 있을 수 있으면 추정하지 않는다(명세 3절 11번)


def test_t45_null_value_with_target_quote_is_not_assumed():
    body = "대상: 3학년. " + BODY
    v = _run({"organizer": "school", "grades": {"value": None, "quote": "대상: 3학년"}, "apply_end": END}, body=body)
    assert v.verdict == "확인 필요"
    r = _reason(v, "grades")
    assert (r.result, r.source) == ("unknown", "unrecognized_value")
    v = _run({"organizer": "school", "grades": {"value": None, "from_image": True}, "apply_end": END})
    assert _reason(v, "grades").source == "unrecognized_value"


def _run_unread(**flags):
    return evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate({"organizer": "school", "apply_end": END}),
        BODY,
        TODAY,
        **flags,
    )


def test_t46_truncated_body_blocks_assumption():
    v = _run_unread(body_truncated=True)
    assert v.verdict == "확인 필요"
    assert "잘려" in _reason(v, "grades").evidence


def test_t47_body_images_block_assumption_until_ai_checks_them():
    v = _run_unread(has_body_images=True)
    assert v.verdict == "확인 필요"
    assert "이미지" in _reason(v, "departments").evidence


def test_t50_checked_images_allow_assumption_but_not_definitively():
    v = evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate({"organizer": "school", "images_checked": True, "apply_end": END}),
        BODY,
        TODAY,
        has_body_images=True,
    )
    assert v.verdict == "가능"
    assert v.confidence == "image_unverified"
    assert _reason(v, "grades").source == "assumed"
    assert "이미지" in _reason(v, "grades").evidence
    assert "확정이 아니" in v.answer_guide


def test_t51_image_values_guide_says_not_definitive():
    body = "대상: 전 학과. " + BODY
    v = _run(
        {
            "grades": {"value": [2], "from_image": True},
            "departments": {"value": "ANY", "quote": "전 학과"},
            "statuses": {"value": ["재학"], "from_image": True},
            "apply_end": END,
        },
        body=body,
    )
    assert (v.verdict, v.confidence) == ("가능", "image_unverified")
    assert "확정이 아니" in v.answer_guide


def test_t48_other_condition_sources_lower_confidence():
    body = "대상: 전 학년 전 학과 재학생. " + BODY
    fields = {
        "grades": {"value": "ANY", "quote": "전 학년"},
        "departments": {"value": "ANY", "quote": "전 학과"},
        "statuses": {"value": ["재학"], "quote": "재학생"},
        "apply_end": END,
    }
    v = _run({**fields, "other_conditions": [{"text": "소득 8분위", "quote": "본문에 없는 문장"}]}, body=body)
    assert v.confidence == "partial"
    v = _run({**fields, "other_conditions": [{"text": "미혼", "from_image": True}]}, body=body)
    assert v.confidence == "image_unverified"


def test_t49_assumed_guide_does_not_say_everyone():
    v = _run({"organizer": "school", "apply_end": END})
    assert "전체 대상" not in v.answer_guide
    assert "추정" in v.answer_guide


# 추정 안내 문구, 교내 공지가 아닐 때의 근거, 근거 없는 참조 표시


def test_t52_assumed_guide_survives_image_confidence():
    v = evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate({"organizer": "school", "images_checked": True, "apply_end": END}),
        BODY,
        TODAY,
        has_body_images=True,
    )
    assert v.confidence == "image_unverified"
    assert "추정" in v.answer_guide and "확정이 아니" in v.answer_guide


def test_t53_blocked_status_evidence_only_for_school_notices():
    v = evaluate(
        parse_profile(PROFILE),
        Extraction.model_validate({"organizer": "external", "apply_end": END}),
        BODY,
        TODAY,
        has_attachments=True,
    )
    assert _reason(v, "statuses").evidence == "공지에서 찾지 못했습니다."
    assert "첨부" in _reason(v, "grades").evidence


def test_t54_empty_refers_elsewhere_does_not_block():
    v = _run({"organizer": "school", "apply_end": END, "refers_elsewhere": {}})
    assert v.verdict == "가능"


def test_t55_null_value_with_quote_not_in_body_is_unverified():
    v = _run({"organizer": "school", "grades": {"value": None, "quote": "대상: 4학년"}, "apply_end": END})
    r = _reason(v, "grades")
    assert (r.result, r.source) == ("unknown", "unverified_quote")


def test_t56_blank_quote_counts_as_no_evidence_but_blank_reference_does_not_block():
    v = _run({"organizer": "school", "grades": {"value": None, "quote": "  "}, "apply_end": END})
    assert _reason(v, "grades").source == "assumed"
    v = _run({"organizer": "school", "apply_end": END, "refers_elsewhere": {"quote": " "}})
    assert v.verdict == "가능"
