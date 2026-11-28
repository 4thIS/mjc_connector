#!/usr/bin/env bash
# 원격 MCP 서버 설치·갱신. 서버에서 root(sudo)로 실행한다.
#
# 사용법: sudo bash install.sh <git 참조(브랜치·태그·커밋)>
#   예: sudo bash install.sh main
#
# 하는 일
#   1. 이 리포를 /opt/mjc/app에 받는다(root 소유, 서비스 사용자 mjc는 읽기만)
#   2. /opt/mjc/venv에 설치한다(pyproject.toml에 고정한 MCP 커밋 포함)
#   3. systemd 서비스 mjc-connector를 깔고 다시 띄운다(127.0.0.1:8001)
#   4. 서버 안에서 도구 목록을 확인한다
# 전제: 서비스 사용자 mjc와 /var/cache/mjc가 있다(서버 기본 설정에서 만든다).
set -euo pipefail

REF="${1:?git 참조를 주세요. 예: sudo bash install.sh main}"
REPO=https://github.com/4thIS/mjc_connector.git
APP=/opt/mjc/app
VENV=/opt/mjc/venv
UNIT=/etc/systemd/system/mjc-connector.service

[ "$(id -u)" -eq 0 ] || { echo "root(sudo)로 실행해야 합니다." >&2; exit 1; }
id mjc >/dev/null 2>&1 || { echo "서비스 사용자 mjc가 없습니다." >&2; exit 1; }

echo "== 1. 코드 받기: ${REF}"
if [ -d "${APP}" ]; then
  mv "${APP}" "${APP}.old.$(date +%Y%m%d%H%M%S)"   # 지우지 않고 옆에 둔다
fi
git clone --quiet "${REPO}" "${APP}"
git -C "${APP}" checkout --quiet "${REF}"
git -C "${APP}" log --oneline -1
chown -R root:mjc "${APP}"
find "${APP}" -type d -exec chmod 750 {} +
find "${APP}" -type f -exec chmod 640 {} +

echo "== 2. 설치"
[ -x "${VENV}/bin/python" ] || python3 -m venv "${VENV}"
"${VENV}/bin/pip" install --quiet --upgrade pip
# 버전 번호가 같아도 고정 커밋이 바뀌면 새 코드가 깔리도록 강제로 다시 설치한다.
"${VENV}/bin/pip" install --quiet --upgrade --force-reinstall "${APP}"
chown -R root:root "${VENV}"
chmod -R o-w "${VENV}"
install -d -m 750 -o mjc -g mjc /var/cache/mjc

echo "== 3. 서비스"
# 1단계 시연 서버(mjc-mcp)가 같은 포트를 쓰고 있으면 끈다. 서비스 파일은 지우지 않는다.
if systemctl list-unit-files mjc-mcp.service >/dev/null 2>&1; then
  systemctl disable --now mjc-mcp >/dev/null 2>&1 || true
fi
install -m 644 "${APP}/deploy/mjc-connector.service" "${UNIT}"
systemctl daemon-reload
systemctl enable mjc-connector >/dev/null
systemctl restart mjc-connector

echo "== 4. 확인"
rollback() {
  echo "새 서비스가 응답하지 않습니다. 새 서비스를 끄고 1단계 시연 서버를 다시 켭니다." >&2
  systemctl disable --now mjc-connector >/dev/null 2>&1 || true
  if systemctl list-unit-files mjc-mcp.service >/dev/null 2>&1; then
    systemctl enable --now mjc-mcp >/dev/null 2>&1 || true
  fi
  echo "원인 확인: journalctl -u mjc-connector -n 50 --no-pager" >&2
  exit 1
}
for _ in $(seq 1 30); do
  LISTEN=$(ss -ltn)
  case "${LISTEN}" in *"127.0.0.1:8001 "*) break ;; esac
  sleep 1
done
# 포트에 떠 있는 것이 새 서비스인지 확인한다(옛 서버가 포트를 쥐고 있으면 실패로 본다).
systemctl is-active --quiet mjc-connector || rollback
NAME=$(curl -s -m 20 -X POST http://127.0.0.1:8001/mcp \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"install-check","version":"0"}}}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["serverInfo"]["name"])') || rollback
[ "${NAME}" = "mjc-connector" ] || rollback
TOOLS=$(curl -s -m 20 -X POST http://127.0.0.1:8001/mcp   -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream'   -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'   | python3 -c 'import json,sys; print(sorted(t["name"] for t in json.load(sys.stdin)["result"]["tools"]))') || rollback
echo "도구: ${TOOLS}"
ss -ltnp | grep ":8001 " || true
echo "상태: systemctl status mjc-connector   기록: journalctl -u mjc-connector -n 50 --no-pager"
