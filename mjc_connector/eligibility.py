"""공지 해당 여부 판정. 규칙은 docs/판정_명세.md를 따른다.

AI(호스트)는 공지에서 조건을 뽑아 근거(본문 인용 또는 "이미지에서 읽음")와 함께
넘기고, 판정은 이 코드가 한다. 근거가 본문에 없거나 값을 알아볼 수 없으면
지어내지 않고 "확인 필요"로 답한다.

evaluate()는 네트워크를 쓰지 않는 순수 함수다. 프로필은 인자로만 받고 저장·로그하지 않는다.
"""

import re
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from common.errors import ToolError
from tools.departments import DEPARTMENTS

Status = Literal["재학", "휴학", "졸업예정"]
STATUSES: frozenset[str] = frozenset(("재학", "휴학", "졸업예정"))
DEPARTMENT_NAMES: frozenset[str] = frozenset(DEPARTMENTS.values())

Result = Literal["match", "mismatch", "unknown", "not_yet"]
Source = Literal["text_quote", "image_read", "missing", "unverified_quote", "unrecognized_value"]

IMAGE_EVIDENCE = "이미지에서 읽은 값입니다. 원본 이미지를 직접 확인하세요."


class Profile(BaseModel):
    department: str = Field(description="정식 학과명(list_departments의 이름 그대로)")
    grade: int = Field(ge=1, le=4, description="학년(1~4)")
    status: Status = Field(description="재학 상태: 재학 / 휴학 / 졸업예정")


class _Evidence(BaseModel):
    quote: str | None = Field(
        default=None, description="이 값의 근거가 되는 공지 본문 원문(그대로 옮겨 적을 것)"
    )
    from_image: bool = Field(
        default=False, description="본문이 아니라 공지 이미지에서 읽은 값이면 true"
    )


class GradeCondition(_Evidence):
    value: list[int] | Literal["ANY"] | None = Field(
        default=None, description='대상 학년 목록. 학년 제한이 없다고 적혀 있으면 "ANY". 못 찾으면 null'
    )


class NameCondition(_Evidence):
    value: list[str] | Literal["ANY"] | None = Field(
        default=None, description='대상 목록. 제한이 없다고 적혀 있으면 "ANY". 못 찾으면 null'
    )


class DateCondition(_Evidence):
    value: date | None = Field(default=None, description="날짜(YYYY-MM-DD). 못 찾으면 null")


class Extraction(BaseModel):
    grades: GradeCondition = Field(default_factory=GradeCondition, description="대상 학년")
    departments: NameCondition = Field(
        default_factory=NameCondition, description="대상 학과(정식 학과명)"
    )
    statuses: NameCondition = Field(
        default_factory=NameCondition, description="대상 재학 상태(재학/휴학/졸업예정)"
    )
    apply_start: DateCondition = Field(default_factory=DateCondition, description="신청 시작일")
    apply_end: DateCondition = Field(default_factory=DateCondition, description="신청 마감일(당일 포함)")


class Reason(BaseModel):
    field: str
    result: Result
    source: Source
    evidence: str


class Deadline(BaseModel):
    date: date
    d_day: int = Field(description="마감까지 남은 날 수. 0이면 오늘 마감")


class Verdict(BaseModel):
    verdict: Literal["가능", "불가", "확인 필요"]
    confidence: Literal["verified", "image_unverified", "partial"] = Field(
        description="verified: 모든 근거가 본문 인용 / image_unverified: 이미지에서 읽은 값이 판정에 "
        "쓰임 / partial: 근거가 없거나 확인되지 않은 값이 있음"
    )
    reasons: list[Reason]
    deadline: Deadline | None = None


def parse_profile(raw: dict) -> Profile:
    """프로필을 검증한다. 오류 문구에는 입력값을 되풀이하지 않는다."""
    try:
        profile = Profile.model_validate(raw)
    except ValidationError:
        raise ToolError(
            "프로필이 올바르지 않습니다. 학과(정식 이름), 학년(1~4), "
            "재학 상태(재학/휴학/졸업예정)를 모두 넘겨 주세요."
        ) from None
    if profile.department not in DEPARTMENT_NAMES:
        raise ToolError("학과가 정식 학과명이 아닙니다. list_departments로 정식 이름을 확인해 주세요.")
    return profile


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _source(condition: _Evidence, body: str) -> Source:
    """값을 믿을 근거가 무엇인지 정한다(명세 3절 2~6번)."""
    if condition.quote and _normalize(condition.quote) in _normalize(body):
        return "text_quote"
    if condition.from_image:
        return "image_read"
    return "unverified_quote"


def _quote_has_date(quote: str, value: date) -> bool:
    """인용에 값의 월·일이 들어 있는지 본다(명세 3절 9번 B 방식).

    `10월 31일`, `10.31`, `10/31`, `2026-10-31`, `11. 6.`처럼 월 다음에 구분자와 일이 오는
    표기를 인정한다. 앞뒤가 숫자인 경우(10.31 안의 10.3)는 일치로 보지 않는다.
    """
    pattern = rf"(?<!\d)0?{value.month}\s*(?:월|[./-])\s*0?{value.day}(?!\d)"
    return re.search(pattern, unicodedata.normalize("NFKC", quote)) is not None


def _evidence(condition: _Evidence, source: Source, note: str = "") -> str:
    if source == "text_quote":
        return condition.quote or ""
    if source == "image_read":
        return IMAGE_EVIDENCE
    return note


def _membership(
    name: str, condition: GradeCondition | NameCondition, actual, allowed: frozenset | None, body: str
) -> Reason:
    if condition.value is None:
        return Reason(field=name, result="unknown", source="missing", evidence="공지에서 찾지 못했습니다.")
    if allowed is not None and condition.value != "ANY":
        if any(item not in allowed for item in condition.value):
            return Reason(
                field=name,
                result="unknown",
                source="unrecognized_value",
                evidence="허용된 값 목록에 없는 표현이라 판정에 쓰지 않았습니다.",
            )
    source = _source(condition, body)
    if source == "unverified_quote":
        return Reason(
            field=name,
            result="unknown",
            source=source,
            evidence="근거 인용이 공지 본문에서 확인되지 않아 판정에 쓰지 않았습니다.",
        )
    matched = condition.value == "ANY" or actual in condition.value
    return Reason(
        field=name,
        result="match" if matched else "mismatch",
        source=source,
        evidence=_evidence(condition, source),
    )


def _date(name: str, condition: DateCondition, today: date, body: str) -> Reason:
    if condition.value is None:
        return Reason(field=name, result="unknown", source="missing", evidence="공지에서 찾지 못했습니다.")
    source = _source(condition, body)
    if source == "unverified_quote":
        return Reason(
            field=name,
            result="unknown",
            source=source,
            evidence="근거 인용이 공지 본문에서 확인되지 않아 판정에 쓰지 않았습니다.",
        )
    # 본문에 있는 인용이라도 그 안에 이 날짜가 없으면 다른 날짜를 근거로 댄 것이다.
    # 이미지에서 읽은 값은 본문 근거가 없으므로 대조하지 않는다.
    if source == "text_quote" and not _quote_has_date(condition.quote or "", condition.value):
        return Reason(
            field=name,
            result="unknown",
            source="unverified_quote",
            evidence="근거 인용에 이 날짜가 들어 있지 않아 판정에 쓰지 않았습니다.",
        )
    if name == "apply_start":
        result: Result = "not_yet" if condition.value > today else "match"
    else:
        result = "mismatch" if condition.value < today else "match"
    return Reason(field=name, result=result, source=source, evidence=_evidence(condition, source))


# 판정에 쓰는 필드. apply_start는 "아직 신청 전" 안내에만 쓴다(명세 4절).
_JUDGED = ("grades", "departments", "statuses", "apply_end")


def evaluate(
    profile: Profile,
    extraction: Extraction,
    body: str,
    today: date,
    posted_on: date | None = None,
) -> Verdict:
    """프로필과 추출값으로 공지 해당 여부를 판정한다.

    posted_on(공지 작성일)은 날짜 교차 검증에서 연도를 보완할 때 쓸 자리다. 아직 쓰지 않는다.
    """
    reasons = [
        _membership("grades", extraction.grades, profile.grade, None, body),
        _membership("departments", extraction.departments, profile.department, DEPARTMENT_NAMES, body),
        _membership("statuses", extraction.statuses, profile.status, STATUSES, body),
        _date("apply_start", extraction.apply_start, today, body),
        _date("apply_end", extraction.apply_end, today, body),
    ]
    judged = [r for r in reasons if r.field in _JUDGED]

    if any(r.result == "mismatch" and r.source == "text_quote" for r in judged):
        verdict = "불가"
    elif any(r.result == "mismatch" for r in judged):
        verdict = "확인 필요"  # 이미지에서 읽은 값만으로는 "불가"를 내리지 않는다
    elif any(r.result == "unknown" for r in judged):
        verdict = "확인 필요"
    else:
        verdict = "가능"

    if any(r.source == "image_read" for r in judged):
        confidence = "image_unverified"
    elif any(r.source in ("missing", "unverified_quote", "unrecognized_value") for r in judged):
        confidence = "partial"
    else:
        confidence = "verified"

    end = next(r for r in reasons if r.field == "apply_end")
    deadline = None
    if end.result in ("match", "mismatch"):
        deadline = Deadline(
            date=extraction.apply_end.value,
            d_day=(extraction.apply_end.value - today).days,
        )

    return Verdict(verdict=verdict, confidence=confidence, reasons=reasons, deadline=deadline)
