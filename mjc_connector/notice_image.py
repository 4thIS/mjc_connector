"""이미지 공지 도구. 공지 본문 이미지를 AI가 읽게 돌려주고, 대화 안에 원본 이미지를 보여 준다.

- get_notice_image: 서버가 학교 이미지를 받아 이미지로 돌려준다(AI가 읽는 용도). 저장하지 않는다.
- show_notice_image: 대화 안 화면(MCP App)에 원본 이미지와 원문 링크를 표시한다.
  이미지는 학생 화면이 학교 서버에서 직접 불러오고, 서버는 주소만 넘긴다.
  화면을 띄우지 못하는 앱에서는 결과의 image_url·source_url을 링크로 안내한다.
- 학교(mjc.ac.kr) https 주소만 허용한다.
- 화면 스크립트(MCP Apps 클라이언트)는 외부 CDN 대신 vendor/ext_apps의 파일을 화면에 그대로 넣는다.
"""

import re
from functools import cache
from importlib import resources
from urllib.parse import urlparse

from common.errors import ToolError
from common.http import fetch
from mcp.server.apps import Apps, ResourceCsp
from mcp.server.mcpserver import Image
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from tools import notices

UI_URI = "ui://mjc/notice-image"
SCHOOL_IMAGE_HOST = "https://mjcms.mjc.ac.kr"
MAX_IMAGE_BYTES = 4_000_000


def _image_url(notice_id: str, index: int) -> str:
    detail = notices.get_notice(notice_id)
    urls = detail.body_images
    if not 0 <= index < len(urls):
        raise ToolError(f"이 공지에는 {index}번 본문 이미지가 없습니다(이미지 {len(urls)}개).")
    url = urls[index]
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "mjc.ac.kr" or host.endswith(".mjc.ac.kr")):
        raise ToolError("학교 이미지 주소가 아니라 가져오지 않았습니다.")
    return url


def _detect_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def get_notice_image(notice_id: str, index: int = 0) -> Image:
    """공지 본문 이미지를 이미지로 돌려준다. notice_id는 search_notices가 돌려준 값을 그대로 넘긴다.

    index는 get_notice 결과 body_images의 순서(0부터)다. 이미지 안의 글(대상·기간 등)을 읽을 때 쓴다.
    이미지에서 읽은 값은 틀릴 수 있으니, 학생에게 전할 때 원본 이미지를 확인하라고 함께 안내한다.
    판정(evaluate_eligibility)에 쓸 때는 from_image를 true로 둔다.
    """
    data = fetch(_image_url(notice_id, index))
    if len(data) > MAX_IMAGE_BYTES:
        raise ToolError("이미지가 너무 커서 가져오지 않았습니다. 원본 이미지 링크를 안내해 주세요.")
    fmt = _detect_format(data)
    if fmt is None:
        raise ToolError("이미지 형식을 알 수 없습니다. 원본 이미지 링크를 안내해 주세요.")
    return Image(data=data, format=fmt)


class NoticeImageView(BaseModel):
    title: str = Field(description="공지 제목")
    image_url: str = Field(description="공지 본문 이미지 주소(학교 서버). 화면이 안 뜨면 이 링크를 안내한다")
    source_url: str = Field(description="공지 원문 페이지 주소")


def show_notice_image(notice_id: str, index: int = 0) -> NoticeImageView:
    """공지 본문 이미지를 학생의 대화 화면에 직접 보여 준다. notice_id는 search_notices가 돌려준 값이다.

    이미지 안의 글을 AI가 읽는 용도가 아니다(읽기는 get_notice_image). 화면을 띄우지 못하는 앱에서는
    결과의 image_url과 source_url을 링크로 안내한다.
    """
    detail = notices.get_notice(notice_id)
    return NoticeImageView(title=detail.title, image_url=_image_url(notice_id, index), source_url=detail.source_url)


_EXPORT_RE = re.compile(r"export\{[^}]*\b(\w+) as App\b[^}]*\};?\s*$")


@cache
def _app_client_script() -> str:
    """리포에 둔 MCP Apps 클라이언트(ES 모듈)의 마지막 export를 전역 변수 대입으로 바꿔 화면에 넣는다."""
    source = (resources.files("mjc_connector") / "vendor/ext_apps/app-with-deps.js").read_text(encoding="utf-8")
    match = _EXPORT_RE.search(source)
    if match is None:
        raise RuntimeError("MCP Apps 클라이언트 스크립트에서 App export를 찾지 못했습니다.")
    return source[: match.start()] + f"globalThis.McpApps={{App:{match.group(1)}}};"


_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="color-scheme" content="light dark"><title>공지 이미지</title>
<style>
  body { font: 14px system-ui, sans-serif; margin: 0; padding: 12px; }
  #title { font-weight: 600; margin-bottom: 8px; }
  img { max-width: 100%; height: auto; border-radius: 8px; display: none; }
  #msg { margin: 8px 0; opacity: .85; }
  a { word-break: break-all; }
</style></head>
<body>
<div id="title">공지 이미지를 불러오는 중…</div>
<img id="img" alt="공지 본문 이미지">
<div id="msg"></div>
<div id="links"></div>
<script>__APP_CLIENT__</script>
<script>
  const $ = (id) => document.getElementById(id);
  const app = new globalThis.McpApps.App({ name: "MJC Notice Image", version: "1.0.0" });
  const addLink = (label, url) => {
    const a = document.createElement("a");
    a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = label;
    const d = document.createElement("div"); d.appendChild(a); $("links").appendChild(d);
  };
  const show = ({ structuredContent: sc }) => {
    if (!sc || !sc.image_url) { $("title").textContent = "표시할 이미지가 없어요."; return; }
    $("title").textContent = sc.title;
    const img = $("img");
    img.onload = () => {
      img.style.display = "block";
      $("msg").textContent = "AI가 읽은 값은 원본과 다를 수 있으니 이미지로 직접 확인해 주세요.";
    };
    img.onerror = () => { $("msg").textContent = "이 화면에서는 이미지를 불러오지 못했어요. 아래 링크로 열어 주세요."; };
    img.src = sc.image_url;
    addLink("원본 이미지 열기", sc.image_url);
    if (sc.source_url) addLink("공지 원문 열기", sc.source_url);
  };
  app.ontoolresult = show;  // 결과 알림을 놓치지 않게 connect 전에 등록한다
  app.connect();
</script>
</body></html>
"""


def page_html() -> str:
    return _PAGE.replace("__APP_CLIENT__", _app_client_script())


apps = Apps()
apps.tool(
    resource_uri=UI_URI,
    title="공지 본문 이미지 화면 표시",
    annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
)(show_notice_image)
apps.add_html_resource(
    UI_URI,
    page_html(),
    title="공지 이미지 화면",
    csp=ResourceCsp(resource_domains=[SCHOOL_IMAGE_HOST]),
    prefers_border=True,
)


def register(mcp) -> None:
    """get_notice_image를 등록한다. show_notice_image는 서버를 만들 때 extensions=[apps]로 붙는다."""
    mcp.tool(
        title="공지 본문 이미지 조회",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
    )(get_notice_image)
