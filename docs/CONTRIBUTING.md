# 작업 규칙

> 2026-10-22 · 팀 전원 대상. 누가 무엇을 어떤 순서로 하는지, 각 작업이 끝나는 조건은 `진행도.md`에 있다. 이 문서는 "어떻게 일하는가"만 다룬다. 일정은 따로 공유한다.
> 표기: **[확인]** 리포에서 직접 확인한 것 / **[제안]** 바꿀 수 있는 기본값(의견이 있으면 말해 달라)

## 1. 작업 대상

- 리포: `https://github.com/4thIS/hackathon_mjc_mcp.git` (기존 MCP 서버). 11/6까지의 공지·학사일정·도서관·테스트 작업은 모두 여기서 한다. [확인: origin 주소]
- 시작 기준 브랜치는 `origin/main`이다. 원격 서버 파일(Dockerfile 등)은 아직 `main`에 없다. 진행도 항목이 그 파일을 건드리라고 하지 않는 한 신경 쓰지 않아도 된다. [확인]
- 두 리포(`hackathon_mjc_mcp`, `mjc_connector`) 모두 `main`은 PR을 거치지 않고는 바뀌지 않게 설정되어 있다(직접 push, 강제 push, 삭제 불가). [확인: 리포 규칙 "Main"]

## 2. 환경 준비

```bash
git clone https://github.com/4thIS/hackathon_mjc_mcp.git
cd hackathon_mjc_mcp
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # macOS/Linux는 .venv/bin/python
.venv/Scripts/python -m pytest tests/ -q
```

- 마지막 명령이 **106 passed**여야 시작할 수 있다. 근거: 2026-10-18 로컬 브랜치에서 106 passed를 확인했고, 그 브랜치와 `origin/main`의 `tests/`는 동일하다. [확인] 다만 `origin/main`을 새로 clone해 돌린 결과는 아니다. PR #15(요청 간격 잠금)가 머지되면 테스트가 2개 늘어 **108 passed**가 된다. [확인: #15 위에서 실행] 106과 108 외의 숫자가 나오면 작업 전에 알려 달라.
- 학교 로그인이 필요한 도구(`search_courses`, `get_syllabus`)와 `auth/login_helper.py`는 이번 작업에 쓰지 않는다.

## 3. 브랜치 규칙

진행도의 상태는 브랜치 이름과 PR에서 자동으로 계산된다(5절). 그래서 브랜치 이름이 규칙을 따라야 한다.

**항목 브랜치** — 진행도 항목 하나에 하나
```
<종류>/<항목 ID>-<주제>
feat/ms-01-notice-filter
test/mj-01-regression-fixtures
```
- `<종류>`: `feat`·`fix`·`docs`·`test`·`chore`·`refactor` 중 하나
- `<주제>`: 영문 소문자·숫자·하이픈
- PR은 **`main`으로** 보낸다. 이 PR이 머지되면 그 항목이 `완료`가 된다.

**분기 브랜치** — 한 항목 안에서 작업을 나눠야 할 때
```
<항목 브랜치>__<부분>
feat/ms-01-notice-filter__sort
feat/ms-01-notice-filter__since
```
- 항목 브랜치 이름 뒤에 밑줄 두 개(`__`)와 부분 이름을 붙인다.
- PR은 **항목 브랜치로** 보낸다(`main`이 아니다). 분기 PR이 모두 항목 브랜치에 머지되면, 항목 브랜치에서 `main`으로 PR을 올린다.
- 슬래시(`/`)로 잇지 않는 이유: git은 `feat/ms-01-notice-filter`와 `feat/ms-01-notice-filter/sort`를 동시에 둘 수 없다(브랜치 이름이 폴더 구조로 저장된다).

```
feat/ms-01-notice-filter__sort  ─PR→  feat/ms-01-notice-filter  ─PR→  main
feat/ms-01-notice-filter__since ─PR→  ┘
```

- 진행도에 없는 일은 브랜치를 만들기 전에 팀장에게 새 항목을 요청한다.
- PR을 올리면 `branch-rules` 검사가 자동으로 돈다. 브랜치 이름이나 PR 대상이 규칙과 다르면 실패하고, 실패한 PR은 `main`에 머지할 수 없다.

## 4. 한 작업의 흐름

1. `진행도.md`의 "지금 상태"에서 자기 항목이 `시작 가능`인지 본다. `선행 대기`면 시작하지 않는다.
2. 항목의 완료 기준·확인된 것·모르는 것을 읽는다. 모르는 용어나 범위가 불분명하면 **코드를 쓰기 전에** 묻는다.
3. `origin/main`에서 3절 규칙대로 항목 브랜치를 만든다.
4. **테스트를 먼저 쓴다.** 새 동작을 검증하는 테스트가 실패하는 것을 확인한 뒤 구현한다.
5. 구현한다. 아래 6·8절에서 건드리지 말라고 한 것은 수정하지 않는다.
6. `pytest tests/ -q` 전체를 돌려 기존 테스트가 하나도 깨지지 않았는지 확인한다.
7. PR을 올린다. **PR 하나는 진행도 항목 하나**다. 본문에 바뀐 것과 테스트 결과(예: `112 passed`)를 적는다.
8. 팀장이 리뷰하고 머지한다.

완료 기준은 진행도 항목의 완료 기준 전부 + 전체 테스트 통과다. "돌아가는 것 같다"는 완료가 아니다.

## 5. 진행 상태

- **진행도의 상태는 손으로 고치지 않는다.** 팀장이 `scripts/progress.py --write`로 PR과 브랜치에서 계산해 갱신한다.
- 계산 규칙: 항목 PR이 `main`에 머지됨 → `완료` / 항목 PR이 열려 있음 → `리뷰 중` / 항목 브랜치가 있거나 분기 PR이 있음 → `작업 중` / 선행이 모두 완료 → `시작 가능` / 그 밖 → `선행 대기`
- 한 PR이 여러 항목을 끝내면 PR 본문 끝에 `진행도: ms-01, ms-02`처럼 적는다. 그 밖에는 브랜치 이름만으로 연결된다.
- 브랜치·PR 규칙을 어긴 경우(분기 PR을 `main`으로 보냄, 이름이 규칙과 다름 등)도 같은 스크립트가 찾아낸다.

## 6. 코드 규칙 (어기면 서버가 깨진다) [확인: 리포 `docs/design.md` 4~6장과 `common/` 코드]

- 어디서든 `print()` 금지. stdout은 MCP 통신 채널이다. 로그는 `logging`(stderr)만.
- HTTP 응답은 `resp.text`가 아니라 bytes(`resp.content`)로 받고, 인코딩 판단은 `common/parse.py`에서만 한다.
- 요청은 `common/http.py`의 `fetch()`로만 한다. 같은 호스트에 1초 간격이 강제된다. 타임아웃과 `follow_redirects=False`를 지킨다.
- 에러는 `common/errors.py`의 `ToolError` 계열을 쓴다. 원문 HTML·헤더·쿠키를 에러에 담지 않는다.
- 도구 반환값은 dict가 아니라 Pydantic `BaseModel`이다. 필드마다 `Field(description=...)`을 쓴다.
- 도구 등록 방식과 `register()`는 건드리지 않는다. 같은 줄을 수정하는 브랜치가 따로 있어 충돌한다. [확인: `title=` 커밋이 `register()`를 바꿨다]
- 테스트 fixture는 실제 응답을 **bytes 원본**으로 저장한다(텍스트로 저장하면 인코딩 버그가 숨는다).

## 7. 커밋과 푸시

- 커밋·푸시 전에 바뀐 내용(`git diff`)을 직접 확인한다. 의도하지 않은 파일(캐시, 개인 설정, 비밀값)이 섞이지 않았는지 본다.
- 메시지 형식은 `<type>: <한국어 제목>`이다. type은 `feat`·`fix`·`docs`·`test`·`refactor`·`chore` 중 하나. [확인: 기존 커밋 관행]
- 변경이 크면 본문에 글머리표로 적는다.

## 8. 하지 않는 것

- 로그인 필요 도구, `auth/`, `common/session.py` 수정. 세션 쿠키·비밀번호를 코드·테스트·로그·PR에 넣는 것.
- 학교 사이트를 테스트용으로 반복 호출하는 것. 필요한 실제 응답은 **한 번만** 받아 fixture로 저장하고, 이후는 fixture로 테스트한다.
- 요청 간격(1초) 제한을 우회하거나 동시 호출로 부하를 주는 것.
- 비밀값이 들어간 파일(`.env`, 키, 토큰)을 만들거나 커밋하는 것. 필요해 보이면 먼저 묻는다.
- 진행도 항목에 없는 개선. 발견한 문제는 PR에 넣지 말고 알려 달라(진행도에 새 항목이 된다).

## 9. 막혔을 때

아래를 같이 보내 주면 한 번에 답할 수 있다.

1. 진행도의 어느 항목인지(예: `ms-01`)
2. 시도한 것과 실제 결과(에러 전문 또는 테스트 출력)
3. 내가 한 가정
