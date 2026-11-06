"""MCP 리포(hackathon_mjc_mcp)를 import 경로에 넣는다.

정식 학과 표와 ToolError는 MCP 리포에 있다. 패키징(진행도 dh-19) 전까지는
옆 폴더의 체크아웃을 경로로 불러오고, 다른 위치면 MJC_MCP_PATH로 지정한다.
"""

import os
import sys
from pathlib import Path

MCP_PATH = Path(
    os.environ.get("MJC_MCP_PATH", Path(__file__).resolve().parents[2] / "hackathon_mjc_mcp")
)
if str(MCP_PATH) not in sys.path:
    sys.path.insert(0, str(MCP_PATH))

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
