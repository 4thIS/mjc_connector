"""진행도 상태를 PR에서 계산한다.

`docs/진행도.md`에는 항목의 변하지 않는 정보(ID·제목·구분·선행·완료 기준)만 적고,
상태는 GitHub PR과 브랜치에서 계산한다. 규칙은 `docs/CONTRIBUTING.md` 3·5절.

    python scripts/progress.py            # 사람별 상태 출력
    python scripts/progress.py --write    # 진행도.md의 상태 블록을 갱신
    python scripts/progress.py --check    # 브랜치·PR 규칙 위반이 있으면 종료 코드 1

필요한 것: GitHub CLI(`gh`)와 두 리포의 읽기 권한.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FILE = ROOT / "docs" / "진행도.md"
DEFAULT_REPOS = ["4thIS/hackathon_mjc_mcp", "4thIS/mjc_connector"]

ID = r"(?:dh|ms|mj|un)-\d{2}"
TYPES = r"(?:feat|fix|docs|test|chore|refactor)"
SLUG = r"[a-z0-9][a-z0-9-]*"
ITEM_BRANCH = re.compile(rf"^{TYPES}/({ID})-{SLUG}$")
SUB_BRANCH = re.compile(rf"^({TYPES}/({ID})-{SLUG})__{SLUG}$")
LOOKS_LIKE_ID = re.compile(rf"(?<![a-z0-9]){ID}(?![0-9])")
BLOCK_START = "<!-- 상태 시작 -->"
BLOCK_END = "<!-- 상태 끝 -->"
PEOPLE = {"dh": "Hyeon02-kr", "ms": "mnzsuu", "mj": "ghl0801", "un": "담당 미정"}


def gh(*args: str) -> str:
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    out = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", **kwargs)
    if out.returncode != 0:
        raise SystemExit(f"gh 실행 실패: {' '.join(args[:3])} — {out.stderr.strip()[:200]}")
    return out.stdout


def load_items(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    items: dict[str, dict] = {}
    for m in re.finditer(rf"^### ({ID}) · (.*?)\n(.*?)(?=^### |^---$|\Z)", text, re.S | re.M):
        item_id, title, body = m.groups()

        def field(name: str) -> str | None:
            f = re.search(rf"^- {name}: (.*)$", body, re.M)
            return f.group(1).strip() if f else None

        items[item_id] = {
            "title": title.strip(),
            "kind": field("구분") or "",
            "deps": LOOKS_LIKE_ID.findall(field("선행") or ""),
            "manual_done": field("완료"),
            "moved_to": field("이동"),
            "pr_links": re.findall(r"(?:([\w.-]+/[\w.-]+))?#(\d+)", field("PR") or ""),
            "prs": [],
            "branch": False,
        }
    return items


def load_repo(repo: str) -> tuple[str, list[dict], list[str]]:
    default = json.loads(gh("repo", "view", repo, "--json", "defaultBranchRef"))["defaultBranchRef"]["name"]
    prs = json.loads(gh("pr", "list", "-R", repo, "--state", "all", "--limit", "300",
                        "--json", "number,state,headRefName,baseRefName,body,url"))
    branches = json.loads(gh("api", f"repos/{repo}/branches", "--paginate", "--jq", "[.[].name]") or "[]")
    for pr in prs:
        pr["repo"] = repo
    return default, prs, branches


def attach(items: dict, repos: list[str]) -> list[str]:
    violations: list[str] = []
    for index, repo in enumerate(repos):
        default, prs, branches = load_repo(repo)
        for name in branches:
            m = ITEM_BRANCH.match(name)
            if m and m.group(1) in items:
                items[m.group(1)]["branch"] = True
        for pr in prs:
            if pr["state"] == "CLOSED":  # 머지 없이 닫힌 PR은 상태에도 위반에도 쓰지 않는다
                continue
            is_open = pr["state"] == "OPEN"
            head, base, ref = pr["headRefName"], pr["baseRefName"], f"{repo}#{pr['number']}"
            item_m, sub_m = ITEM_BRANCH.match(head), SUB_BRANCH.match(head)
            ids: set[str] = set()
            role = None
            if item_m:
                ids.add(item_m.group(1))
                role = "item"
                if base != default and is_open:
                    violations.append(f"{ref}: 항목 브랜치 `{head}`의 PR은 `{default}`로 보내야 한다(지금 `{base}`)")
            elif sub_m:
                ids.add(sub_m.group(2))
                role = "sub"
                if base != sub_m.group(1) and is_open:
                    violations.append(f"{ref}: 분기 브랜치 `{head}`의 PR은 항목 브랜치 `{sub_m.group(1)}`로 보내야 한다(지금 `{base}`)")
            elif LOOKS_LIKE_ID.search(head) and is_open:
                violations.append(f"{ref}: 브랜치 이름 `{head}`이 규칙(`<종류>/<ID>-<주제>` 또는 `…__<부분>`)과 다르다")
            body_ids = re.search(rf"진행도:\s*((?:{ID}[,\s]*)+)", pr.get("body") or "")
            if body_ids:
                ids |= set(LOOKS_LIKE_ID.findall(body_ids.group(1)))
                role = role or "item"
            for item_id, item in items.items():
                for link_repo, number in item["pr_links"]:
                    if (link_repo or repos[0]) == repo and int(number) == pr["number"]:
                        ids.add(item_id)
                        role = role or "item"
            for item_id in ids:
                if item_id not in items:
                    if is_open:
                        violations.append(f"{ref}: `{item_id}`가 진행도에 없다")
                    continue
                items[item_id]["prs"].append({**pr, "role": role, "to_default": base == default})
    return violations


def resolve(items: dict, item_id: str) -> str:
    """이동 표기를 따라가 실제로 일이 진행되는 항목 ID를 돌려준다."""
    seen = set()
    while item_id in items and items[item_id]["moved_to"] and item_id not in seen:
        seen.add(item_id)
        target = LOOKS_LIKE_ID.search(items[item_id]["moved_to"])
        if not target:
            break
        item_id = target.group(0)
    return item_id


def check_moves(items: dict) -> list[str]:
    violations = []
    for item_id, item in items.items():
        if item["moved_to"]:
            target = LOOKS_LIKE_ID.search(item["moved_to"])
            if not target or target.group(0) not in items:
                violations.append(f"`{item_id}`의 이동 대상 `{item['moved_to']}`이 진행도에 없다")
                continue
            chain, current = [item_id], target.group(0)
            while current in items and items[current]["moved_to"] and current not in chain:
                chain.append(current)
                nxt = LOOKS_LIKE_ID.search(items[current]["moved_to"])
                current = nxt.group(0) if nxt else ""
            if current == item_id:
                violations.append(f"`{item_id}`의 이동이 순환한다({' → '.join(chain + [item_id])})")
    return violations


def status(items: dict, item_id: str, memo: dict) -> str:
    if item_id in memo:
        return memo[item_id]
    item = items[item_id]
    prs = item["prs"]
    if item["moved_to"]:
        result = f"이동({item['moved_to']})"
    elif item["kind"].startswith("범위 밖"):
        result = "보류"
    elif item["manual_done"] or any(p["state"] == "MERGED" and p["role"] == "item" and p["to_default"] for p in prs):
        result = "완료"
    elif any(p["state"] == "OPEN" and p["role"] == "item" and p["to_default"] for p in prs):
        result = "리뷰 중"
    elif item["branch"] or any(
        p["state"] == "OPEN" or (p["role"] == "sub" and p["state"] == "MERGED") for p in prs
    ):
        result = "작업 중"
    else:
        memo[item_id] = "…"  # 순환 방지
        deps: dict[str, str] = {}  # 옮겨진 선행은 옮겨 간 항목으로 판단하고, 표시는 "원래→옮겨 간" 형태로 한다
        for d in item["deps"]:
            deps.setdefault(resolve(items, d), d)
        waiting = [d if d == orig else f"{orig}→{d}" for d, orig in deps.items()
                   if d in items and status(items, d, memo) != "완료"]
        result = "시작 가능" if not waiting else "선행 대기(" + ", ".join(waiting) + ")"
    memo[item_id] = result
    return result


def render(items: dict) -> str:
    memo: dict[str, str] = {}
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"> 자동 계산: {now} · `python scripts/progress.py --write`로 갱신한다. 이 블록은 손으로 고치지 않는다.", ""]
    for who, name in PEOPLE.items():
        ids = [i for i in items if i.startswith(who)]
        if not ids:
            continue
        lines.append(f"**{who} · {name}**")
        for i in ids:
            prs = ", ".join(sorted({f"#{p['number']}" for p in items[i]["prs"]}))
            pr_text = f" ({prs})" if prs else ""
            lines.append(f"- `{i}` {status(items, i, memo)}{pr_text} — {items[i]['title']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="진행도 상태를 PR에서 계산한다.")
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--repo", action="append", help="조회할 리포(여러 번 지정 가능). 첫 리포가 `PR: #번호`의 기본값")
    parser.add_argument("--write", action="store_true", help="진행도.md의 상태 블록을 갱신한다")
    parser.add_argument("--check", action="store_true", help="규칙 위반이 있으면 종료 코드 1")
    args = parser.parse_args()

    items = load_items(args.file)
    violations = check_moves(items) + attach(items, args.repo or DEFAULT_REPOS)
    block = render(items)

    if args.write:
        text = args.file.read_text(encoding="utf-8")
        if BLOCK_START not in text or BLOCK_END not in text:
            raise SystemExit(f"{args.file.name}에 상태 블록 표시({BLOCK_START} … {BLOCK_END})가 없다")
        head, rest = text.split(BLOCK_START, 1)
        _, tail = rest.split(BLOCK_END, 1)
        args.file.write_text(f"{head}{BLOCK_START}\n{block}{BLOCK_END}{tail}", encoding="utf-8")
        print(f"갱신: {args.file}")
    else:
        print(block)

    if violations:
        print("규칙 위반:")
        for v in violations:
            print(f"- {v}")
    return 1 if (args.check and violations) else 0


if __name__ == "__main__":
    raise SystemExit(main())
