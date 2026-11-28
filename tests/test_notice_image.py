"""이미지 공지 도구 테스트. 학교 사이트로 요청하지 않도록 조회 함수를 바꿔 둔다."""

import asyncio

import pytest
from common.errors import ToolError
from common.models import NoticeDetail
from mcp.client import Client

from mjc_connector import notice_image, server

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
SCHOOL_IMG = "https://mjcms.mjc.ac.kr/upload/poster.png"


def _detail(images):
    return NoticeDetail(
        title="장학 포스터",
        department="학생복지팀",
        posted_on="2026-11-01",
        views=1,
        body="본문이 이미지로만 작성된 공지입니다.",
        body_images=images,
        attachments=[],
        truncated=False,
        source_url="https://www.mjc.ac.kr/bbs/data/view.do?x=1",
    )


@pytest.fixture
def notice(monkeypatch):
    def use(images, data=PNG):
        monkeypatch.setattr(notice_image.notices, "get_notice", lambda notice_id: _detail(images))
        monkeypatch.setattr(notice_image, "fetch", lambda url: data)

    return use


def test_returns_school_image_as_image(notice):
    notice([SCHOOL_IMG])
    image = notice_image.get_notice_image("1:BM1:BD1")
    assert image.data == PNG


@pytest.mark.parametrize(
    "url",
    ["http://mjcms.mjc.ac.kr/a.png", "https://evil.example.com/a.png", "https://mjc.ac.kr.evil.com/a.png"],
)
def test_rejects_non_school_image_addresses(notice, url):
    notice([url])
    with pytest.raises(ToolError):
        notice_image.get_notice_image("1:BM1:BD1")
    with pytest.raises(ToolError):
        notice_image.show_notice_image("1:BM1:BD1")


def test_rejects_missing_index_large_and_unknown_images(notice):
    notice([SCHOOL_IMG])
    with pytest.raises(ToolError):
        notice_image.get_notice_image("1:BM1:BD1", index=1)
    notice([SCHOOL_IMG], data=b"\x89PNG\r\n\x1a\n" + b"0" * notice_image.MAX_IMAGE_BYTES)
    with pytest.raises(ToolError):
        notice_image.get_notice_image("1:BM1:BD1")
    notice([SCHOOL_IMG], data=b"<html>not an image</html>")
    with pytest.raises(ToolError):
        notice_image.get_notice_image("1:BM1:BD1")


def test_show_returns_links_for_apps_without_screens(notice):
    notice([SCHOOL_IMG])
    view = notice_image.show_notice_image("1:BM1:BD1")
    assert (view.image_url, view.source_url) == (SCHOOL_IMG, "https://www.mjc.ac.kr/bbs/data/view.do?x=1")


def test_screen_does_not_load_scripts_from_outside():
    html = notice_image.page_html()
    assert "unpkg" not in html and "<script src" not in html and "import " not in html.split("<script>")[-1]
    assert "globalThis.McpApps={App:" in html


def test_server_exports_image_tools_and_screen():
    async def check():
        async with Client(server.mcp) as client:
            names = {tool.name for tool in (await client.list_tools()).tools}
            resources = {str(r.uri) for r in (await client.list_resources()).resources}
            return names, resources

    names, resources = asyncio.run(check())
    assert {"get_notice_image", "show_notice_image"} <= names
    assert notice_image.UI_URI in resources
