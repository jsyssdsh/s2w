#!/usr/bin/env bash
# 오프라인 안전 제어 호스트 테스트 (SPEC 6 / ARCHITECTURE 11.3).
#
# 툴체인도 실물 보드도 필요 없다 — lib/farmcontrol 은 순수 C++ 이라 아무
# 컴파일러로나 빌드된다. PlatformIO 가 깔려 있으면 `pio test -e native` 가
# 같은 파일을 돌린다.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$(mktemp -d)"
trap 'rm -rf "$out"' EXIT

"${CXX:-c++}" -std=c++17 -Wall -Wextra -Werror -O1 \
  -I "$here/lib/farmcontrol" \
  "$here/lib/farmcontrol/offline_control.cpp" \
  "$here/test/test_offline_control/test_offline_control.cpp" \
  -o "$out/test_offline_control"

"$out/test_offline_control"
