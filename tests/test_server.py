"""원격 진입점 테스트: 내보내는 도구, 로그인 코드 미포함, 바인딩 주소, 허용 Host."""

import asyncio
import subprocess
import sys

from mcp.client import Client

from mjc_connector import server

EXPECTED_TOOLS = {"search_notices", "get_notice", "get_library_seats", "list_departments", "get_notice_image", "show_notice_image"}


def test_exports_only_public_tools():
    async def names():
        async with Client(server.mcp) as client:
            return {tool.name for tool in (await client.list_tools()).tools}

    assert asyncio.run(names()) == EXPECTED_TOOLS


def test_login_code_is_not_imported():
    code = (
        "import sys; import mjc_connector.server; "
        "bad = [m for m in sys.modules if m == 'auth' or m.startswith('auth.') "
        "or m in ('common.session', 'tools.course_search', 'tools.syllabus')]; print(bad)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "[]"


def test_binds_only_inside_the_server():
    assert server.HOST == "127.0.0.1"


def test_public_hosts_are_added_to_local_hosts():
    settings = server.transport_security("mjc-mcp.example.dev, other.example.dev")
    assert settings.enable_dns_rebinding_protection
    assert settings.allowed_hosts == server.LOCAL_HOSTS + ["mjc-mcp.example.dev", "other.example.dev"]
    assert server.transport_security("").allowed_hosts == server.LOCAL_HOSTS
