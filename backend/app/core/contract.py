"""조건의 **판**(계약 판) — CompCore 점 파일의 `conditions` 가 아는 모양인가(2026-11-25).

CompCore 는 조건을 케이스 여럿(v2, `cases[]`)으로 넓힌다(CompCore ADR 0013). 우리는 판을 보지
않아서, v2 가 오면 거절하지 않고 맨 위의 빈 자리를 읽었다 — 「조건_볼트예압_정적」 을 v2
모양으로 바꿔 넣으니 **구속 0 · 하중 0 · 해석 종류 modal** 이었다. 모달이면 자유-자유 해석이
끝까지 돌고 그 결과는 오류 없이 그럴듯하다.

**모르는 판이면 조건을 통째로 안 읽고 막는다.** 「CAD 가 보낸 조건 사용」 을 꺼도 막는다 —
그때도 같은 블록에서 물성 · 단위 · 기준 온도 · 쉘 두께를 읽는데, 판이 다르면 그것들이 어디
있는지도 모른다(v2 는 초기조건을 케이스 안으로 옮긴다 — 기준 온도가 조용히 22 °C 가 된다).

**판을 적지 않은 것은 1 로 읽는다.** CompCore 는 처음부터 점 파일에 `schema_version: 1` 을
적으므로 (픽스처의 점 파일 전부) 안 적은 것은 손으로 만든 파일이다 — 막으면 그것들이 못 쓰게
된다. 대신 모양(`cases`)으로도 본다. `study.json` 의 조건 요약에는 판이 없지만 우리는 그것을
조건으로 안 읽는다.

막는 자리는 넷이다: 폴더의 설계점(`doe/folder.py`) · 작업 만들기(`services.create` · DOE
가져오기) · 두 솔버의 모델링(이 검사가 없던 때 걸린 작업) · 조건 읽기(`conditions.read` —
화면의 미리 보기).
"""

from __future__ import annotations

from typing import Any

from app.core.stages import StageFailure

#: 읽을 수 있는 조건의 판. v2(케이스 여럿)를 받게 되면 여기 더하고 읽는 길을 만든다.
VERSIONS: tuple[int, ...] = (1,)
#: 판을 적는 칸 — 지금 CompCore 는 `schema_version`, 설계 문서(해석-확장-설계 2장)는 `version`
#: 이다. 어느 쪽에 적어도 알아본다(칸 이름이 정해지기 전에 온 것도 막아야 한다).
KEYS = ("schema_version", "version")


def problem(payload: Any) -> str | None:
    """조건의 판이 모르는 것이면 **사람이 읽을 까닭**, 읽을 수 있으면(조건이 없어도) `None`."""
    block = payload.get("conditions") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None
    for key in KEYS:
        declared = block.get(key)
        if declared is None or _known(declared):
            continue
        return (
            f"조건의 판({key} = {declared!r})을 이 서버가 읽지 못합니다(읽는 판: "
            f"{' · '.join(str(one) for one in VERSIONS)}) — CompCore 에서 케이스 하나인 "
            "조건으로 다시 내보내거나 이 서버를 갱신하세요."
        )
    cases = block.get("cases")
    if cases:
        # 판을 안 적고 모양만 바뀐 것 — 맨 위의 구속 · 하중이 비어 「조건 없음」 으로 읽힌다.
        count = f" {len(cases)}개" if isinstance(cases, list | dict) else ""
        return (
            f"해석 케이스{count}로 나눈 조건을 이 서버가 읽지 못합니다 — CompCore 에서 케이스 "
            "하나인 조건으로 다시 내보내거나 이 서버를 갱신하세요."
        )
    return None


def _known(declared: Any) -> bool:
    """`1` · `1.0` 은 1 이다. 참 · 거짓과 글자는 판이 아니다."""
    return (
        isinstance(declared, int | float)
        and not isinstance(declared, bool)
        and declared in VERSIONS
    )


def require(payload: Any) -> None:
    """모델링의 문 — 모르는 판이면 멈춘다."""
    found = problem(payload)
    if found:
        raise StageFailure("region_unresolved", found)
