# 작업카드 03 — 공지 본문 종류 필드 `kind` (`get_notice`)

> 담당: mnzsuu(서브 개발) · 리포: `hackathon_mjc_mcp` · 절차는 `개발절차서.md`
> 상태: 초안 · 팀장 확인 전. **[확인]** 리포에서 직접 확인 / **[제안]** 팀장이 정한 기본안(바꿔도 된다)
> **선행: 카드 01이 병합된 뒤에 시작한다.** 같은 함수(`parse_notice_detail`)의 본문 만드는 부분을 건드리기 때문에 먼저 시작하면 충돌한다.

## 목표

`get_notice` 결과에 본문의 종류를 알려 주는 구조화된 필드 `kind`를 추가한다. 이후 판정 기능이 이 필드로 텍스트 공지와 이미지 공지를 구분한다.

## 배경

- 지금은 본문이 이미지뿐인 공지를 구분하려면 `body`에 들어간 안내 문구(`_IMAGE_ONLY_BODY`)를 읽어야 한다. 텍스트가 없으면 항상 이 문구가 들어가므로, 이미지도 텍스트도 없는 공지에도 "이미지로 작성되었다"는 문구가 나간다. [확인: `parse_notice_detail`의 `body_images`·본문 처리]
- 2026-10-10 조회에서 공지 72건 중 이미지 전용이 22건(31%)이었고 장학 공지는 18건 중 12건이었다. 이 구분이 판정의 신뢰도 경로를 가른다.

## 요구사항

1. `NoticeDetail`에 `kind` 필드를 추가한다. 타입은 `Literal["text", "mixed", "image_only", "empty"] | None`, 기본값 `None`. [제안]
   - `text`: 본문 텍스트가 있고 이미지가 없다
   - `mixed`: 본문 텍스트와 이미지가 모두 있다
   - `image_only`: 본문 텍스트가 없고 이미지가 있다
   - `empty`: 본문 텍스트도 이미지도 없다
2. 판정은 안내 문구를 끼우기 **전의** 본문 텍스트(카드 01에서 만든 평탄화 결과의 공백 제거 후)가 비었는지, `body_images`가 비었는지로 한다.
3. `body` 동작은 바꾸지 않는다. 단 `kind == "empty"`일 때는 이미지 안내 문구 대신 "본문이 비어 있습니다. source_url에서 원문을 직접 확인하세요" 취지의 다른 문구를 쓴다. [제안] `text`·`mixed`·`image_only`는 지금과 같다.
4. 기존 캐시(필드 없음)는 `kind=None`으로 읽혀야 한다.
5. 필드 `description`에 AI가 읽을 수 있게 네 값의 뜻을 적는다. (`common/models.py`)

## 입력(fixture)

- 이미지 전용: 기존 `tests/fixtures/notice_detail.html`(이미지 전용 공지, 테스트가 `body_images`를 단언한다 [확인])
- 텍스트 전용·혼합: 카드 01에서 만든 fixture를 재사용한다. 혼합(텍스트+이미지) 사례가 없으면 인라인 HTML 바이트로 만든다(기존 `test_relative_image_src_becomes_absolute_url` 방식).
- 빈 본문: 인라인 HTML(`<div class='board_view'><div id='divMemo'></div></div>`)

## 완료 기준 (전부 만족)

- [ ] 새 테스트가 먼저 실패하는 것을 확인했다
- [ ] 네 값 각각을 검증하는 테스트가 있다(이미지 전용은 기존 fixture, 나머지는 위 입력)
- [ ] 이미지 전용·텍스트 전용 공지의 `body`가 이전과 같다(기존 테스트가 그대로 통과)
- [ ] `empty`일 때 `body`가 이미지 안내 문구가 아니다
- [ ] 옛 캐시가 `kind=None`으로 로드된다(`test_cached_detail_without_new_fields_still_loads`와 같은 방식의 테스트)
- [ ] 전체 테스트 통과(기존 106개 + 01·02 이후 늘어난 개수 포함)

## 건드리지 말 것

- `register()`, `search_notices`, `NoticeSummary`(카드 02), `common/` 중 `models.py`의 `NoticeDetail` 외 부분

## 하지 않는 것

- 이미지 URL을 AI에게 이미지로 돌려주는 기능(이후 G2 실험 결과에 따라 팀장이 한다)
- 첨부 파일 텍스트 추출, 링크 목록 분리

## 막히면

`개발절차서.md` 7절 형식으로 팀장에게 보낸다.
