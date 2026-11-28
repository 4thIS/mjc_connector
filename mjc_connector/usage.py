"""시험 운영 기록. 도구 호출을 개인정보 없이 한 줄씩 남긴다(알파·베타 테스트의 사용 통계용).

정해 둔 칸만 적는다. 입력값(프로필·검색어·공지 ID·추출값)과 접속 주소는 처음부터 기록에 넣지 않는다.
- ts: 분 단위 시각(KST), tool: 도구 이름, ok: 성공 여부, error: 실패한 예외 종류, ms: 걸린 시간
- 판정 도구만 verdict(가능/불가/확인 필요)·confidence를 더한다

환경 변수 MJC_USAGE_LOG에 파일 경로를 주면 켜지고, 없거나 비어 있으면 아무것도 적지 않는다.
기록에 실패해도 도구 응답은 그대로 나간다.
"""

import functools
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_logger = logging.getLogger(__name__)


def _write(entry: dict) -> None:
    path = os.environ.get("MJC_USAGE_LOG")
    if not path:
        return
    entry = {"ts": datetime.now(KST).strftime("%Y-%m-%dT%H:%M"), **entry}
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as error:
        _logger.warning("시험 운영 기록을 쓰지 못했습니다: %s", type(error).__name__)


def _wrap(name: str, fn):
    @functools.wraps(fn)
    def run(**kwargs):
        entry: dict = {"tool": name}
        start = time.monotonic()
        try:
            result = fn(**kwargs)
        except Exception as error:
            entry.update(ok=False, error=type(error).__name__)
            raise
        else:
            entry["ok"] = True
            if name == "evaluate_eligibility":
                entry.update(verdict=result.verdict, confidence=result.confidence)
            return result
        finally:
            entry["ms"] = round((time.monotonic() - start) * 1000)
            _write(entry)

    return run


def instrument(mcp) -> None:
    """등록된 도구마다 기록을 단다. 도구 등록을 모두 마친 뒤 한 번 부른다."""
    for tool in mcp._tool_manager.list_tools():
        tool.fn = _wrap(tool.name, tool.fn)
