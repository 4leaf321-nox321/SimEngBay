"""`<이름>-<id8>/` 한 벌을 읽는다.

    study.json                    기준 레시피 · 인자 정의 · 시드
    manifest.csv                  점 · 상태 · 바꾼 변수 · 파일 둘 · 못 푼 영역
    conditions.json               조건(중립 표현, 식이 있는 그대로 — 사람이 읽는 정본)
    points/pNNNN.json             **이 점의 모든 것** — point · bodies · regions · conditions
    points/pNNNN.step             그 점만 쓰는 형상
    shapes/<지문>.step             **여러 점이 나눠 쓰는 형상**(조건만 훑었을 때)

## 파일 이름을 짐작하지 않는다

어느 점이 어느 STEP 을 쓰는지는 **표의 `step_file`** 이 말한다. 조건만 훑으면 형상이 전부
같아서 CAD 가 한 벌만 두고 `shapes/` 를 가리킨다 — 「점 번호로 이름을 지으면 된다」 고 믿으면
그 폴더에서 파일을 못 찾는다(CompCore 가 2026-09-24 에 계약을 그렇게 바꿨다).

**같은 경로를 가리키는 점들은 같은 형상이다.** 그래서 모델링 · 메시도 한 번만 하면 된다 —
`recipe_digest` 를 따로 볼 필요가 없다.

## CSV 가 정본이다

파일 이름만으로는 치수를 되짚을 수 없다 — 「p0007.step 이 두께 몇짜리인가」 에 답하는 것은
`manifest.csv` 뿐이다(CompCore 가 CSV 를 둔 이유도 같다). 그래서 이 모듈은 **CSV 를 기준으로**
점을 세고, 파일은 그 줄이 가리키는 대로 찾는다.

**BOM 을 달고 온다.** 엑셀이 한글을 깨지 않게 CompCore 가 붙인다 — `utf-8-sig` 로 읽지 않으면
첫 열 이름이 `﻿point` 가 되고, 그러면 점 번호를 못 찾는다(조용히 0건이 된다).

## 단위 선언을 함께 읽는다

점 파일에 `conditions.units.system` 이 온다 — 그 값을 읽지 않으면 mm 계로 온 숫자를 MKS
세션에 넣고도 **아무 오류가 안 난다**(고유진동수만 10³ 배 틀린다). 그래서 여기서 읽어 두고,
**모르는 계면 그 점을 걸 수 없는 것으로 본다** — 모델링까지 가서 실패하면 200점이 같은 실패를
한 번씩 하고, 사람은 그걸 로그에서 센다. 세우는 일은 `app/core/units.py` 가 한다.

## 못 쓰는 점을 걸지 않는다 — 대신 **몇 개를 왜 건너뛰는지 말한다**

설계점 200개를 보내 놓고 「왜 절반이 실패했지」 를 로그에서 찾게 하지 않는다. CompCore 가
`unresolved` · `status` 열을 만든 이유와 같다.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core import units

MANIFEST = "manifest.csv"
STUDY = "study.json"

#: 표의 고정 열. 이것 말고는 전부 **바꾼 변수**다(인자 이름은 스터디마다 다르다).
#: `topology` 는 옛 이름이다 — 계약이 `point_file` 로 바뀌었지만, 이미 내보낸 폴더가 디스크에
#: 남아 있을 수 있어 열 이름으로는 둘 다 안다.
FIXED_COLUMNS = frozenset(
    {
        "point",
        "status",
        "step_file",
        "point_file",
        "topology",
        "unresolved",
        "interference",
        "error",
    }
)


#: 설계점에서 바꾼 값 하나. **숫자만이 아니다** — 재료처럼 고르는 인자가 온다(CompCore 가
#: 물성 DOE 를 붙이면서 들어온다). 숫자로 안 읽히면 **글자 그대로 들고 간다**: 버리면 두
#: 설계점이 화면에서 똑같아 보이고, 사람은 왜 결과가 다른지 알 방법이 없다.
ParamValue = float | str


@dataclass
class DoePoint:
    """설계점 하나 — 걸 수 있는 것과, 걸 수 없다면 그 이유."""

    number: int
    params: dict[str, ParamValue]
    step: Path | None = None
    point_file: Path | None = None
    """`pNNNN.json` — 영역 · 바디 · 설계점 메타 · 조건이 한 파일에 있다."""
    status: str = "ok"
    unresolved: list[str] = field(default_factory=list)
    error: str = ""
    #: 같은 형상인지 되짚는 열쇠 — **STEP 경로 그 자체다.** 나눠 쓰는 형상은 여러 점이 같은
    #: `shapes/<지문>.step` 을 가리키므로, 경로가 같으면 형상도 같다.
    shape_key: str = ""
    #: 이 점에 조건(`conditions`)이 실려 있나. 없으면 사람이 화면에서 채워야 한다.
    has_conditions: bool = False
    #: CAD 가 선언한 단위계 이름 그대로(`conditions.units.system`). 비어 있으면 선언이 없다 —
    #: 그때는 SI 로 본다(`app/core/units.py`).
    unit_system: str = ""
    #: 걸 수 없는 이유. 비어 있으면 걸 수 있다.
    skip_reason: str = ""

    @property
    def usable(self) -> bool:
        return not self.skip_reason


@dataclass
class DoeFolder:
    path: Path
    study_id: str
    name: str
    factors: list[str]
    points: list[DoePoint]
    seed: int | None = None
    method: str = ""

    @property
    def usable(self) -> list[DoePoint]:
        return [one for one in self.points if one.usable]

    @property
    def skipped(self) -> list[DoePoint]:
        return [one for one in self.points if not one.usable]


class FolderProblem(Exception):
    """폴더를 아예 읽을 수 없다 — 경로가 틀렸거나 DOE 폴더가 아니다."""


def _value(raw: str | None) -> ParamValue | None:
    """표의 칸 하나. 숫자로 읽히면 숫자, 아니면 **글자 그대로**. 빈 칸은 없는 값이다."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return text


def read_folder(path: Path) -> DoeFolder:
    """폴더 한 벌을 읽는다. **파일이 없으면 여기서 말한다** — 반쯤 읽고 0건을 내지 않는다."""
    if not path.is_dir():
        raise FolderProblem(f"폴더가 없습니다: {path}")
    manifest = path / MANIFEST
    if not manifest.is_file():
        raise FolderProblem(
            f"{MANIFEST} 이 없습니다 — CAD 가 내보낸 DOE 폴더인지 확인하세요: {path}"
        )

    study: dict[str, Any] = {}
    study_path = path / STUDY
    if study_path.is_file():
        try:
            study = json.loads(study_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as failure:
            raise FolderProblem(f"{STUDY} 을 읽지 못했습니다: {failure}") from failure

    # **BOM 을 달고 온다**(모듈 머리말). utf-8 로 읽으면 첫 열 이름이 깨진다.
    text = manifest.read_text(encoding="utf-8-sig")
    rows = list(csv.DictReader(text.splitlines()))
    if not rows:
        raise FolderProblem(f"{MANIFEST} 에 설계점이 없습니다.")

    columns = [name for name in rows[0] if name]
    factors = [name for name in columns if name not in FIXED_COLUMNS]

    points = [_point(path, row, factors) for row in rows]
    return DoeFolder(
        path=path,
        study_id=str(study.get("id") or ""),
        name=str(study.get("name") or path.name),
        factors=factors,
        points=points,
        seed=study.get("seed"),
        method=str(study.get("method") or ""),
    )


def _point(folder: Path, row: dict[str, str], factors: list[str]) -> DoePoint:
    number = int(row.get("point") or 0)
    params = {name: value for name in factors if (value := _value(row.get(name))) is not None}
    status = (row.get("status") or "").strip()
    unresolved = [one for one in (row.get("unresolved") or "").split() if one]
    error = (row.get("error") or "").strip()

    step = _resolve(folder, row.get("step_file"))
    # `topology` 는 옛 이름 — 이미 내보낸 폴더를 위해 함께 본다.
    point_file = _resolve(folder, row.get("point_file") or row.get("topology"))

    has_conditions = False
    unit_system = ""
    if point_file is not None:
        try:
            loaded = json.loads(point_file.read_text(encoding="utf-8"))
            conditions = loaded.get("conditions")
            has_conditions = bool(conditions)
            if isinstance(conditions, dict):
                declared = (conditions.get("units") or {}).get("system")
                unit_system = str(declared or "").strip()
        except (OSError, json.JSONDecodeError):
            has_conditions = False

    point = DoePoint(
        number=number,
        params=params,
        step=step,
        point_file=point_file,
        status=status or "ok",
        unresolved=unresolved,
        error=error,
        # **경로가 곧 형상의 열쇠다**(모듈 머리말). 표의 값을 그대로 쓴다 — 우리가 다시
        # 지으면 나눠 쓰는 형상에서 어긋난다.
        shape_key=(row.get("step_file") or "").strip(),
        has_conditions=has_conditions,
        unit_system=unit_system,
    )
    point.skip_reason = _skip_reason(point, row)
    return point


def _resolve(folder: Path, relative: str | None) -> Path | None:
    """표가 가리킨 파일. **폴더 밖을 가리키면 없는 것으로 본다** — 표는 남이 만든 파일이다."""
    if not relative:
        return None
    target = (folder / relative).resolve()
    if folder.resolve() not in target.parents:
        return None
    return target if target.is_file() else None


def _skip_reason(point: DoePoint, row: dict[str, str]) -> str:
    """걸 수 없는 이유 한 줄. **비어 있으면 걸 수 있다.**"""
    if point.status not in ("ok", ""):
        return point.error or f"CAD 에서 실패한 점입니다({point.status})"
    if point.step is None:
        return f"형상 파일이 없습니다({row.get('step_file') or '표에 비어 있음'})"
    if point.unresolved:
        # 영역을 못 풀었으면 경계조건을 붙일 자리가 없다. 그대로 걸면 구속 없는 해석이 돈다.
        return f"CAD 가 풀지 못한 영역이 있습니다: {' · '.join(point.unresolved)}"
    if point.unit_system and point.unit_system not in units.KNOWN:
        # **모르는 계로 온 값은 아무 계에도 넣지 않는다.** 여기서 막아야 200점을 걸어 놓고
        # 모델링마다 같은 실패를 보는 일이 없다 — 미리보기에서 이 줄을 읽는다.
        return (
            f"이 플랫폼이 모르는 단위계입니다: {point.unit_system} "
            f"(아는 것: {' · '.join(sorted(units.KNOWN))})"
        )
    return ""
