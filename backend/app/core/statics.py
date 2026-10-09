"""정적 해석을 **무엇으로 풀 것인가** — 큰 변형 · 초기 부단계 수. 솔버가 둘이라 여기 둔다.

조화 응답의 `harmonic.harmonic_plan` 과 같은 자리다 — 스펙과 CAD 조건을 한 자리에서 합쳐야
Ansys 경로와 CalculiX 경로가 **같은 설정으로** 풀고, 요약이 같은 것을 말한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core import conditions as condition_model
from app.core.spec import StaticSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticPlan:
    """큰 변형을 켜나 · 비선형을 몇 걸음으로 시작하나.

    **사람이 적었으면 그것, 비웠으면 CAD 가 적은 것이다.** 전에는 CAD 의
    `analysis.large_deflection` 을 두 솔버 모두 읽지 않아, CompCore 시험 규격 20개 중
    6개(굽힘 · 핀 베어링 · 이음 · 비틀림)가 「큰 변형」 이라 적었는데도 선형으로
    풀렸다(2026-10-08). 새 작업 창은 CAD 값을 미리 채워 보내므로, 사람이 바꾼 것만 CAD 와
    다르다.
    """

    large_deflection: bool
    #: 초기 부단계 수 — CAD 가 적었을 때만. 비선형 단계에서만 뜻이 있다.
    substeps: int | None
    #: 큰 변형을 누가 정했나 — `spec` · `cad` · `default`(둘 다 안 적음 — 끈다).
    source: str


def static_plan(spec: StaticSpec, given: condition_model.Conditions) -> StaticPlan:
    """스펙과 CAD 조건을 합쳐 실제로 풀 정적 설정을 낸다."""
    declared = given.analysis
    if spec.large_deflection is not None:
        large, source = spec.large_deflection, "spec"
    elif declared.large_deflection is not None:
        large, source = declared.large_deflection, "cad"
    else:
        large, source = False, "default"
    if source == "cad":
        logger.info("큰 변형 ← CAD: %s", "켬" if large else "끔")
    return StaticPlan(large_deflection=large, substeps=declared.substeps, source=source)
