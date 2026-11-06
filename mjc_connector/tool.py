"""MCP 도구 evaluate_eligibility. 본문은 서버가 직접 다시 가져온다(호스트가 넘긴 본문은 쓰지 않는다)."""

from datetime import date, datetime, timedelta, timezone

from mcp.types import ToolAnnotations
from pydantic import ValidationError

from common.errors import ToolError
from mjc_connector.eligibility import Extraction, Profile, Verdict, evaluate, parse_profile
from tools import notices

KST = timezone(timedelta(hours=9))


def evaluate_eligibility(notice_id: str, profile: Profile, extraction: Extraction) -> Verdict:
    """학교 공지가 이 학생에게 해당되는지 판정한다. 판정은 이 도구(코드)가 한다.

    쓰는 순서:
    1. get_notice로 공지를 읽는다. 본문이 이미지인 공지는 이미지에서 읽은 값을 쓴다.
    2. 공지에서 대상 학년·학과·재학 상태와 신청 시작·마감일을 찾아 extraction에 넣는다.
       - 각 값의 근거가 되는 본문 문장을 quote에 **원문 그대로** 옮겨 적는다. 바꿔 쓰면 근거로 인정되지 않는다.
       - 날짜의 quote에는 그 날짜(월·일)가 적힌 부분을 넣는다. 다른 날짜가 적힌 문장은 근거로 인정되지 않는다.
       - 이미지에서 읽은 값이면 quote 대신 from_image를 true로 둔다.
       - 제한이 없다고 적혀 있으면 value를 "ANY"로 두고, 그렇게 적힌 본문 문장을 quote에 넣는다.
         이미지에서만 읽은 "제한 없음"은 "ANY"로 인정되지 않는다.
       - 찾지 못한 값은 null로 둔다(빈 목록은 보내지 않는다). 추측해서 채우지 않는다.
       - 학과는 list_departments의 정식 이름으로, 재학 상태는 재학/휴학/졸업예정으로만 쓴다.
    3. profile에는 학생이 직접 말한 학과(정식 이름)·학년·재학 상태만 넣는다. 묻지 않고 지어내지 않는다.

    결과의 verdict는 "가능" / "불가" / "확인 필요"다. reasons의 근거와 deadline(마감·D-day)을 함께
    전하고, 이미지에서 읽은 값이 쓰였으면(confidence가 image_unverified) 원본을 확인하라고 안내한다.
    이 판정은 공지 원문을 대신하지 않으므로, 최종 확인은 원문과 담당 부서로 하도록 안내한다.

    판정이 보는 것은 대상 학년·학과·재학 상태와 신청 기간뿐이다. 공지에 그 밖의 조건(소득, 나이,
    자격증, 증명서 등)이 있으면 판정에 들어가지 않으므로, "가능"이어도 그 조건을 따로 알려 준다.
    """
    checked = parse_profile(profile.model_dump())
    detail = notices.get_notice(notice_id)  # 조회 실패는 ToolError로 올라간다(판정을 지어내지 않는다)
    try:
        posted_on = date.fromisoformat(detail.posted_on)
    except ValueError:
        posted_on = None
    today = datetime.now(KST).date()
    return evaluate(checked, extraction, detail.body, today, posted_on)


def _hide_input_values(arg_model: type) -> type:
    """SDK의 인자 검증 오류를 입력값 없는 ToolError로 바꾸는 인자 모델을 만든다.

    pydantic 검증 오류 문구는 입력값(input_value)을 그대로 담아 프로필이 오류에 남는다.
    걸린 인자의 위치만 알려 준다(명세 1절 입력 형태, T21).
    """

    class HiddenInputArguments(arg_model):
        @classmethod
        def model_validate(cls, obj, *args, **kwargs):
            try:
                return super().model_validate(obj, *args, **kwargs)
            except ValidationError as error:
                where = ", ".join(sorted({".".join(map(str, e["loc"])) for e in error.errors()}))
                raise ToolError(
                    f"인자 형식이 올바르지 않습니다({where}). profile은 학과(정식 이름)·학년(1~4)·"
                    "재학 상태(재학/휴학/졸업예정), extraction은 도구 설명의 형식을 따라 주세요."
                ) from None

    HiddenInputArguments.__name__ = arg_model.__name__
    return HiddenInputArguments


def register(mcp) -> None:
    mcp.tool(
        title="공지 해당 여부 판정",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )(evaluate_eligibility)
    # MCPServer에는 인자 검증 오류를 바꿀 공개 설정이 없어 등록된 도구의 인자 모델을 감싼다.
    registered = mcp._tool_manager.get_tool("evaluate_eligibility")
    registered.fn_metadata.arg_model = _hide_input_values(registered.fn_metadata.arg_model)
