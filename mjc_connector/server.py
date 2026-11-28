"""원격 MCP 서버 진입점(Streamable HTTP).

로그인 없이 볼 수 있는 공개 정보 도구(공지·도서관·학과·학사일정)만 등록한다. 로그인이 필요한 도구(강좌 검색·강의계획서)와
로그인 도우미는 불러오지 않는다. 여러 학생의 계정·세션을 다루는 문제는 별도 설계가 필요하다.

- 서버 안쪽 주소(127.0.0.1)에만 열고, 공개는 앞단의 터널이 맡는다.
- 요청 간격 제한(common/http.py)이 프로세스 메모리에 있으므로 프로세스는 하나만 띄운다.

환경 변수
- PORT: 열 포트(기본 8001)
- MJC_PUBLIC_HOSTS: 터널이 넘기는 공개 주소(쉼표로 여러 개). 이 주소의 Host만 추가로 허용한다
- MJC_CACHE_DIR: 대체 캐시 폴더(hackathon_mjc_mcp의 common/cache.py)
"""

import logging
import os
import sys

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from tools import academic_calendar, departments, library_seats, notices

HOST = "127.0.0.1"
LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]

mcp = MCPServer("mjc-connector")
library_seats.register(mcp)
notices.register(mcp)
departments.register(mcp)
academic_calendar.register(mcp)


def transport_security(public_hosts: str | None = None) -> TransportSecuritySettings:
    """서버 안쪽 주소에 더해 공개 주소의 Host만 허용한다(DNS 리바인딩 방어는 유지)."""
    raw = os.environ.get("MJC_PUBLIC_HOSTS", "") if public_hosts is None else public_hosts
    extra = [host.strip() for host in raw.split(",") if host.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=LOCAL_HOSTS + extra,
        allowed_origins=LOCAL_ORIGINS,
    )


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    mcp.run(
        transport="streamable-http",
        host=HOST,
        port=int(os.environ.get("PORT", "8001")),
        json_response=True,
        stateless_http=True,
        transport_security=transport_security(),
    )


if __name__ == "__main__":
    main()
