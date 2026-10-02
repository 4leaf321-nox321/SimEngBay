"""추출 단계 — CalculiX 의 `.dat` 에서 고유진동수를 읽는다.

**결과 모양은 Ansys 쪽과 같다**(`app/core/dpf/extract.py`). 화면 · 스터디 비교 · 모드 추적이 그
모양을 읽으므로, 솔버가 바뀌었다고 다른 모양을 내면 전부 손봐야 한다. 그래서 같은 열쇠를 쓰고,
**아직 없는 것은 넣지 않는다** — 유효질량비 · 모드 형상은 2단계다. 비어 있는 것과 0 은 다르다.

`result.json` 에 **어느 솔버로 풀었는지 도장을 찍는다.** 두 솔버의 수가 몇 % 갈리므로(실측
2026-10-02: 1차 1,266.4 대 1,263.5 Hz), 그 도장이 없으면 「어제와 값이 다르다」 가 영구
미해결로 남는다.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.core.spec import RIGID_BODY_MODES, ModalSpec
from app.core.stages import ArtifactSpec, StageFailure, StageResult

logger = logging.getLogger(__name__)

RESULT_NAME = "result.json"
DATA_NAME = "model.dat"
BOUNDARY_NAME = "boundary.json"

#: 이보다 낮으면 강체 모드로 본다 — Ansys 쪽과 같은 문턱(수치 오차로 0 이 정확히 0 이 아니다).
RIGID_BODY_HZ = 1.0
#: `.dat` 의 고유치 표 머리말. 그 아래 줄은 **다섯 칸**이다(실측 2026-10-02):
#: `모드 / 고유치 / rad·s⁻¹ / Hz / 허수부`. 네 번째가 Hz 다 — 칸 수를 넷으로 못 박으면 한 줄도
#: 안 읽힌다(그렇게 해 봤다).
EIGEN_HEAD = "E I G E N V A L U E   O U T P U T"
_ROW = re.compile(r"^\s*(\d+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+\S+)*\s*$")


def extract(spec: ModalSpec, workdir: Path, **_ignored: object) -> StageResult:
    """`model.dat` → `result.json`."""
    data = workdir / DATA_NAME
    if not data.is_file():
        raise StageFailure("solver_failed", f"결과 파일이 없습니다: {DATA_NAME}")

    values = frequencies(data.read_text(encoding="utf-8", errors="replace"))
    if not values:
        raise StageFailure(
            "solver_failed",
            f"{DATA_NAME} 에서 고유진동수를 못 읽었습니다 — 솔버 로그를 보세요.",
        )
    constrained, mesh = _declared(workdir)
    modes: list[dict[str, Any]] = []
    elastic_index = 0
    for index, value in enumerate(values, start=1):
        rigid = value < RIGID_BODY_HZ
        if not rigid:
            elastic_index += 1
        modes.append(
            {
                "number": index,
                "elastic_number": None if rigid else elastic_index,
                "frequency_hz": round(value, 4),
                "rigid_body": rigid,
            }
        )
    rigid_found = sum(1 for one in modes if one["rigid_body"])
    elastic = [one for one in modes if not one["rigid_body"]]

    result: dict[str, Any] = {
        "recipe": "modal",
        "solver": "calculix",
        "boundary": "constrained" if constrained else "free-free",
        # 덱을 mm · tonne · N 으로 쓰므로 주파수는 Hz 다(`calculix/deck.py`).
        "units": {"frequency": "Hz", "system": "ConsistentNMM"},
        "normalization": "mass",
        "rigid_body_modes": rigid_found,
        **({"mesh": mesh} if mesh else {}),
        "modes": modes,
    }
    if not constrained and rigid_found != RIGID_BODY_MODES:
        # **세어 보고 다르면 적어 둔다.** 바디가 여럿인데 접합면이 안 붙었으면 강체 모드가
        # 바디마다 6개씩 나온다 — 값은 그럴듯한데 모델이 떨어져 있는 상태다.
        result["warning"] = (
            f"자유-자유인데 강체 모드가 {rigid_found}개입니다(6개여야 합니다). "
            f"맞닿은 면이 붙지 않았을 수 있습니다."
        )

    path = workdir / RESULT_NAME
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    first = elastic[0]["frequency_hz"] if elastic else None
    return StageResult(
        artifacts=[ArtifactSpec("result_json", path)],
        summary={
            "solver": "calculix",
            "modes": len(modes),
            "rigid_body_modes": rigid_found,
            "first_elastic_hz": first,
            # 모드 형상은 아직 안 만든다 — 0 이라고 적어 화면이 「없다」 를 알게 한다.
            "mode_shapes": 0,
        },
        detail=f"모드 {len(modes)}개" + (f" · 1차 탄성 {first} Hz" if first else ""),
    )


def frequencies(text: str) -> list[float]:
    """`.dat` 의 고유진동수(Hz) 목록.

    표의 네 번째 칸이 Hz 다(첫 칸 모드 번호 · 둘째 고유치 · 셋째 rad/s · 다섯째 허수부). 표
    뒤에 **참여계수 표**가 이어지므로 **빈 줄에서 끊는다** — 안 끊으면 그 숫자까지 모드로 읽어
    0 Hz 가 줄줄이 붙는다(실측 2026-10-02, 스파이크에서 그랬다).

    그 참여계수 표는 2단계에서 쓸 값이다 — 방향별 유효질량비를 거기서 낼 수 있다(Ansys 쪽
    `app/core/dpf/participation.py` 가 하는 일).
    """
    head = text.find(EIGEN_HEAD)
    if head < 0:
        return []
    found: list[float] = []
    started = False
    for line in text[head + len(EIGEN_HEAD) :].splitlines():
        row = _ROW.match(line)
        if row:
            started = True
            found.append(float(row.group(4)))
            continue
        if started and not line.strip():
            break
    return found


def _declared(workdir: Path) -> tuple[bool, dict[str, int]]:
    """모델링이 남긴 것 — 구속 여부와 메시 크기. **없으면 비워 둔다**(지어내지 않는다)."""
    path = workdir / BOUNDARY_NAME
    constrained = True
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            constrained = bool(loaded.get("constrained", True))
        except (OSError, ValueError):
            logger.warning("%s 를 읽지 못했습니다", BOUNDARY_NAME)
    mesh: dict[str, int] = {}
    msh = workdir / "model.msh"
    if msh.is_file():
        counts = msh.read_text(encoding="utf-8", errors="replace")
        nodes = re.search(r"\$Nodes\s*\n\s*(\d+)", counts)
        elements = re.search(r"\$Elements\s*\n\s*(\d+)", counts)
        if nodes:
            mesh["nodes"] = int(nodes.group(1))
        if elements:
            mesh["elements"] = int(elements.group(1))
    return constrained, mesh
