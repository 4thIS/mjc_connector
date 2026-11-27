"""공지 해당 여부 판정. 규칙은 docs/판정_명세.md를 따른다.

AI(호스트)는 공지에서 조건을 뽑아 근거(본문 인용 또는 "이미지에서 읽음")와 함께
넘기고, 판정은 이 코드가 한다. 근거가 본문에 없거나 값을 알아볼 수 없으면
지어내지 않고 "확인 필요"로 답한다.

evaluate()는 네트워크를 쓰지 않는 순수 함수다. 프로필은 인자로만 받고 저장·로그하지 않는다.
"""

import re
import unicodedata
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError

from common.errors import ToolError
from tools.departments import DEPARTMENTS

Status = Literal["재학", "휴학", "졸업예정"]
STATUSES: frozenset[str] = frozenset(("재학", "휴학", "졸업예정"))
DEPARTMENT_NAMES: frozenset[str] = frozenset(DEPARTMENTS.values())

Result = Literal["match", "mismatch", "unknown", "not_yet"]
Source = Literal[
    "text_quote", "image_read", "missing", "unverified_quote", "unrecognized_value", "assumed"
]

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


# 빈 목록은 뜻이 정해지지 않아 입력 오류로 거절한다. 못 찾은 값은 null이다(명세 2절).
_Grades = Annotated[list[int], Field(min_length=1)]
_Names = Annotated[list[str], Field(min_length=1)]


class GradeCondition(_Evidence):
    value: _Grades | Literal["ANY"] | None = Field(
        default=None, description='대상 학년 목록. 학년 제한이 없다고 적혀 있으면 "ANY". 못 찾으면 null'
    )


class NameCondition(_Evidence):
    value: _Names | Literal["ANY"] | None = Field(
        default=None, description='대상 목록. 제한이 없다고 적혀 있으면 "ANY". 못 찾으면 null'
    )


class DateCondition(_Evidence):
    value: date | None = Field(default=None, description="날짜(YYYY-MM-DD). 못 찾으면 null")


class OtherCondition(_Evidence):
    text: str = Field(description="판정 범위 밖 조건 한 가지(예: 만 39세 이하, 소득 8분위 이하, 미혼)")


class Extraction(BaseModel):
    organizer: Literal["school", "external"] | None = Field(
        default=None,
        description="공지한 프로그램을 학교가 운영하면 school, 외부 기관이면 external, 알 수 없으면 null",
    )
    grades: GradeCondition = Field(default_factory=GradeCondition, description="대상 학년")
    departments: NameCondition = Field(
        default_factory=NameCondition, description="대상 학과(정식 학과명)"
    )
    statuses: NameCondition = Field(
        default_factory=NameCondition, description="대상 재학 상태(재학/휴학/졸업예정)"
    )
    apply_start: DateCondition = Field(default_factory=DateCondition, description="신청 시작일")
    apply_end: DateCondition = Field(default_factory=DateCondition, description="신청 마감일(당일 포함)")
    other_conditions: list[OtherCondition] = Field(
        default_factory=list,
        description="학년·학과·재학 상태·신청 기간 밖의 자격 조건(나이, 소득, 성적, 이전 수혜, 혼인 등). 없으면 빈 목록",
    )
    images_checked: bool = Field(
        default=False,
        description="본문 이미지를 모두 읽고(get_notice_image) 대상 문구를 확인했으면 true. 이미지가 없으면 무시된다",
    )
    refers_elsewhere: _Evidence | None = Field(
        default=None,
        description="대상·조건을 다른 공지나 별도 문서에서 보라고 적혀 있으면 그 문장(quote 또는 from_image). 없으면 null",
    )


class Reason(BaseModel):
    field: str
    result: Result
    source: Source
    evidence: str


class OtherConditionResult(BaseModel):
    text: str = Field(description="판정에 넣지 않은 자격 조건(AI가 공지에서 뽑은 그대로)")
    source: Source = Field(description="근거 종류: text_quote(본문 인용 확인) / image_read(이미지에서 읽음) / unverified_quote(확인 안 됨)")
    evidence: str = Field(description="본문 인용, 이미지 확인 안내, 또는 근거가 확인되지 않았다는 안내")


class Deadline(BaseModel):
    date: date
    d_day: int = Field(description="마감까지 남은 날 수. 0이면 오늘 마감")


class Verdict(BaseModel):
    verdict: Literal["가능", "불가", "확인 필요"]
    confidence: Literal["verified", "image_unverified", "partial", "assumed"] = Field(
        description="verified: 모든 근거가 본문 인용 / image_unverified: 이미지에서 읽은 값이 판정에 "
        "쓰임 / partial: 근거가 없거나 확인되지 않은 값이 있음 / assumed: 공지에 적혀 있지 않은 대상을 "
        "규칙으로 채움(추정)"
    )
    reasons: list[Reason]
    deadline: Deadline | None = None
    other_conditions: list[OtherConditionResult] = Field(
        default_factory=list,
        description="판정에 넣지 않은 자격 조건. 하나라도 있으면 \"가능\" 대신 \"확인 필요\"가 된다",
    )
    attachment_status: Literal["none", "not_read"] = Field(
        default="none", description="none: 첨부 없음 / not_read: 첨부가 있지만 판정에서 읽지 않음"
    )
    answer_guide: str = Field(default="", description="학생에게 답할 때 지킬 표현 수준")


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


def _has_evidence(condition: _Evidence) -> bool:
    """공백만 있는 인용은 근거로 보지 않는다."""
    return bool(condition.quote and condition.quote.strip()) or condition.from_image


def _normalize(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def _source(condition: _Evidence, body: str) -> Source:
    """값을 믿을 근거가 무엇인지 정한다(명세 3절 2~6번)."""
    # 공백만 있는 인용은 정규화하면 빈 문자열이라 어디에나 "있게" 되므로 근거로 보지 않는다.
    if condition.quote and condition.quote.strip() and _normalize(condition.quote) in _normalize(body):
        return "text_quote"
    if condition.from_image:
        return "image_read"
    return "unverified_quote"


def _quote_has_date(quote: str, value: date) -> bool:
    """인용에 값의 월·일이 들어 있는지 본다(명세 3절 9번 B 방식, dh-11에서 C 방식으로 교체).

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


# 공지에 대상이 적혀 있지 않을 때의 해석(명세 3절 11번, 2026-11-21 결정)
_ASSUMED_ALL = {
    "grades": "공지에 대상 학년이 적혀 있지 않아 전체 학년 대상으로 봤습니다(추정).",
    "departments": "공지에 대상 학과가 적혀 있지 않아 전체 학과 대상으로 봤습니다(추정).",
}
_ASSUMED_ENROLLED = "교내 공지에 대상 재학 상태가 적혀 있지 않아 재학생 대상으로 봤습니다(추정)."
_NOT_ASSUMED_ATTACHMENT = "공지에 적혀 있지 않고, 읽지 않은 첨부 파일에 있을 수 있어 대상을 추정하지 않았습니다."
_NOT_ASSUMED_ELSEWHERE = "공지가 대상·조건을 다른 곳에서 보라고 안내해, 대상을 추정하지 않았습니다."
_NOT_ASSUMED_TRUNCATED = "공지 본문이 길어 잘려서, 잘린 부분에 대상이 있을 수 있어 추정하지 않았습니다."
_NOT_ASSUMED_IMAGES = "공지 본문에 이미지가 있는데 이미지를 읽었다는 표시가 없어, 이미지에 대상이 있을 수 있어 추정하지 않았습니다."
_IMAGE_CHECKED_NOTE = " 본문 이미지는 AI가 읽은 결과에 기대므로 원본 이미지를 확인하세요."
_NOT_MAPPED = "대상을 적은 근거는 있지만 값으로 옮기지 못해 판정에 쓰지 않았습니다."

# 판정 수준에 맞는 답변 표현. 설명이 판정보다 앞서 나가지 않게 한다(명세 5절)
_GUIDE = {
    "가능": "신청할 수 있다고 안내하되 근거와 마감일을 함께 전한다.",
    "불가": "신청할 수 없다고 안내하고 그 사유를 근거와 함께 전한다.",
    "확인 필요": "\"할 수 있다\", \"해당될 것 같다\"처럼 가능을 암시하는 표현을 쓰지 않는다. "
    "무엇이 확인되지 않았는지와 확인할 곳(원문·담당 부서)을 전한다.",
}
_GUIDE_ASSUMED = " 대상 일부는 공지에 적혀 있지 않아 규칙으로 추정했으니, 그 점과 reasons의 추정 근거를 함께 말한다."
_GUIDE_ATTACHMENT = " 첨부 파일은 읽지 않았으니 첨부도 확인하라고 안내한다."
_GUIDE_IMAGE = " 이미지에서 읽은 내용에 기댄 결과라 확정이 아니므로, 원본 이미지를 직접 확인하라고 안내한다."


def _membership(
    name: str,
    condition: GradeCondition | NameCondition,
    actual,
    allowed: frozenset | None,
    body: str,
    assumed: tuple[list | str, str] | str | None = None,
) -> Reason:
    """assumed는 값이 null일 때 대신 쓸 (대상 값, 근거 문장)이다.

    None이면 null은 unknown이고, 문자열이면 추정하지 않은 이유를 담은 unknown이다.
    """
    if condition.value is None:
        # 근거(인용·이미지)를 달았는데 값이 없으면 대상이 적혀 있다는 뜻이다. 추정하지 않는다.
        if _has_evidence(condition):
            if _source(condition, body) == "unverified_quote":
                return Reason(
                    field=name,
                    result="unknown",
                    source="unverified_quote",
                    evidence="근거 인용이 공지 본문에서 확인되지 않아 판정에 쓰지 않았습니다.",
                )
            return Reason(field=name, result="unknown", source="unrecognized_value", evidence=_NOT_MAPPED)
        if assumed is None or isinstance(assumed, str):
            evidence = assumed or "공지에서 찾지 못했습니다."
            return Reason(field=name, result="unknown", source="missing", evidence=evidence)
        target, evidence = assumed
        matched = target == "ANY" or actual in target
        # 추정한 대상과 맞지 않아도 "불가"로 만들지 않는다(4절: text_quote mismatch만 불가).
        return Reason(field=name, result="match" if matched else "mismatch", source="assumed", evidence=evidence)
    if allowed is not None and condition.value != "ANY":
        if any(item not in allowed for item in condition.value):
            return Reason(
                field=name,
                result="unknown",
                source="unrecognized_value",
                evidence="허용된 값 목록에 없는 표현이라 판정에 쓰지 않았습니다.",
            )
    source = _source(condition, body)
    # "ANY"(제한 없음)는 본문에서 확인된 인용이 있을 때만 인정한다. 이미지에서 읽은 "ANY"도 쓰지 않는다.
    if source == "unverified_quote" or (condition.value == "ANY" and source != "text_quote"):
        return Reason(
            field=name,
            result="unknown",
            source="unverified_quote",
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


def _other_condition(condition: OtherCondition, body: str) -> OtherConditionResult:
    source = _source(condition, body)
    if _has_evidence(condition):
        note = "근거 인용이 공지 본문에서 확인되지 않았습니다. 원문을 확인하세요."
    else:
        note = "근거가 없습니다. 원문에서 이 조건을 확인하세요."
    return OtherConditionResult(text=condition.text, source=source, evidence=_evidence(condition, source, note))


# 판정에 쓰는 필드. apply_start는 "아직 신청 전" 안내에만 쓴다(명세 4절).
_JUDGED = ("grades", "departments", "statuses", "apply_end")


def evaluate(
    profile: Profile,
    extraction: Extraction,
    body: str,
    today: date,
    posted_on: date | None = None,
    has_attachments: bool = False,
    body_truncated: bool = False,
    has_body_images: bool = False,
) -> Verdict:
    """프로필과 추출값으로 공지 해당 여부를 판정한다.

    posted_on(공지 작성일)은 날짜 교차 검증에서 연도를 보완할 때 쓸 자리다. 아직 쓰지 않는다.
    """
    # 대상이 첨부나 다른 공지에 있을 수 있으면 추정하지 않는다(명세 3절 11번).
    blocked = None
    elsewhere = extraction.refers_elsewhere
    if elsewhere is not None and _has_evidence(elsewhere):
        blocked = _NOT_ASSUMED_ELSEWHERE
    elif has_attachments:
        blocked = _NOT_ASSUMED_ATTACHMENT
    elif body_truncated:
        blocked = _NOT_ASSUMED_TRUNCATED
    elif has_body_images and not extraction.images_checked:
        blocked = _NOT_ASSUMED_IMAGES
    if blocked:
        assume_grades = assume_departments = blocked
        # 재학 상태는 교내 공지에서만 추정하므로, 그 밖의 공지에는 막은 이유를 붙이지 않는다.
        enrolled = blocked if extraction.organizer == "school" else None
    else:
        # 이미지가 있는 공지는 AI가 이미지를 읽고 대상이 없다고 확인한 경우에만 추정한다. 확정이 아니다.
        note = _IMAGE_CHECKED_NOTE if has_body_images else ""
        assume_grades = ("ANY", _ASSUMED_ALL["grades"] + note)
        assume_departments = ("ANY", _ASSUMED_ALL["departments"] + note)
        enrolled = (["재학"], _ASSUMED_ENROLLED + note) if extraction.organizer == "school" else None
    reasons = [
        _membership("grades", extraction.grades, profile.grade, None, body, assume_grades),
        _membership(
            "departments", extraction.departments, profile.department, DEPARTMENT_NAMES, body, assume_departments
        ),
        _membership("statuses", extraction.statuses, profile.status, STATUSES, body, enrolled),
        _date("apply_start", extraction.apply_start, today, body),
        _date("apply_end", extraction.apply_end, today, body),
    ]
    judged = [r for r in reasons if r.field in _JUDGED]
    # 내용 없는 조건(공백)은 학생에게 전할 것이 없으므로 판정에서 뺀다.
    others = [_other_condition(c, body) for c in extraction.other_conditions if c.text.strip()]

    if any(r.result == "mismatch" and r.source == "text_quote" for r in judged):
        verdict = "불가"
    elif any(r.result == "mismatch" for r in judged):
        verdict = "확인 필요"  # 이미지에서 읽은 값만으로는 "불가"를 내리지 않는다
    elif any(r.result == "unknown" for r in judged):
        verdict = "확인 필요"
    elif others:
        verdict = "확인 필요"  # 판정 범위 밖 조건은 코드가 확인할 수 없다(명세 4절 4번)
    else:
        verdict = "가능"

    sources = [r.source for r in judged] + [c.source for c in others]
    image_assumed = has_body_images and "assumed" in sources
    if "image_read" in sources or image_assumed:
        confidence = "image_unverified"
    elif any(s in ("missing", "unverified_quote", "unrecognized_value") for s in sources):
        confidence = "partial"
    elif "assumed" in sources:
        confidence = "assumed"
    else:
        confidence = "verified"

    end = next(r for r in reasons if r.field == "apply_end")
    deadline = None
    if end.result in ("match", "mismatch"):
        deadline = Deadline(
            date=extraction.apply_end.value,
            d_day=(extraction.apply_end.value - today).days,
        )

    guide = _GUIDE[verdict]
    if verdict != "불가" and any(r.source == "assumed" for r in judged):
        guide += _GUIDE_ASSUMED
    if verdict == "가능" and confidence == "image_unverified":
        guide += _GUIDE_IMAGE
    if has_attachments:
        guide += _GUIDE_ATTACHMENT
    return Verdict(
        verdict=verdict,
        confidence=confidence,
        reasons=reasons,
        deadline=deadline,
        other_conditions=others,
        attachment_status="not_read" if has_attachments else "none",
        answer_guide=guide,
    )
