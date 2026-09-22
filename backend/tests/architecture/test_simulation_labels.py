"""서버가 만드는 코드값에 화면의 이름표가 있는가.

상태 · 단계 · 실패 코드 · 산출물 종류는 **서버가 정본**이고 화면은 이름표를 단다. 코어에 코드를
하나 더하고 화면을 안 고치면 사람은 목록에서 `region_unresolved` 같은 날것을 읽는다 — 그리고
그것은 아무것도 말해 주지 않는다. 여기서 잡지 않으면 그 회귀는 화면을 눈으로 볼 때만 드러난다.

프론트가 없는 설치(백엔드만 받은 경우)는 건너뛴다.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.stages import STAGES
from app.modules.simulations.models import STATUSES

BACKEND = Path(__file__).resolve().parents[2]
FRONTEND = BACKEND.parent / "frontend" / "src"
LABELS = FRONTEND / "modules" / "simulations" / "labels.ts"
BADGE = FRONTEND / "shared" / "components" / "StatusBadge.tsx"
STAGES_PY = BACKEND / "app" / "core" / "stages.py"


def _literals(source: str, name: str) -> set[str]:
    """`FailureCode = Literal["a", "b"]` 같은 선언에서 문자열들을 뽑는다."""
    body = re.search(rf"{name}\s*=\s*Literal\[(.*?)\]", source, re.S)
    assert body is not None, f"{name} 선언을 찾지 못했습니다"
    return set(re.findall(r'"([a-z_]+)"', body.group(1)))


def _keys(source: str, table: str) -> set[str]:
    """`const X: Record<…> = { a: …, b: … }` 의 열쇠들."""
    body = re.search(rf"{table}[^=]*=\s*\{{(.*?)\n\}}", source, re.S)
    assert body is not None, f"{table} 표를 찾지 못했습니다"
    return set(re.findall(r"^\s{2}([a-z_]+):", body.group(1), re.M))


def test_상태와_단계와_실패코드에_화면_이름표가_있다() -> None:
    if not LABELS.exists():  # pragma: no cover - 백엔드만 받은 설치
        return
    labels = LABELS.read_text(encoding="utf-8")
    badge = BADGE.read_text(encoding="utf-8")
    stages_source = STAGES_PY.read_text(encoding="utf-8")

    missing_status = set(STATUSES) - _keys(badge, "const SIMULATION")
    assert not missing_status, f"StatusBadge 에 없는 작업 상태: {sorted(missing_status)}"

    missing_stage = set(STAGES) - _keys(labels, "export const STAGE_LABELS")
    assert not missing_stage, f"labels.ts 에 없는 단계: {sorted(missing_stage)}"

    missing_failure = _literals(stages_source, "FailureCode") - _keys(
        labels, "export const FAILURE_LABELS"
    )
    assert not missing_failure, f"labels.ts 에 없는 실패 코드: {sorted(missing_failure)}"

    missing_artifact = _literals(stages_source, "ArtifactKind") - _keys(
        labels, "export const ARTIFACT_LABELS"
    )
    assert not missing_artifact, f"labels.ts 에 없는 산출물 종류: {sorted(missing_artifact)}"
