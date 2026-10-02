"""조화 응답을 **무엇으로 풀 것인가** — 솔버가 둘이라 여기 둔다.

범위 · 점 수 · 감쇠비를 스펙과 CAD 조건에서 합쳐 한 자리에서 정한다. Ansys 경로와 CalculiX
경로가 **같은 값으로** 풀어야 교차 검증이 뜻을 가지고, 결과 · 요약 · 덱이 같은 것을 말한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.core import conditions as condition_model
from app.core.spec import HarmonicSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HarmonicPlan:
    """조화 응답을 **무엇으로 풀 것인가** — 범위 · 점 수 · 감쇠비.

    **CAD 가 적어 보내면 그것이 먼저다.** 스펙 기본값으로 조용히 덮으면 CAD 가
    「200~2000 Hz · 90점 · 2%」 라고 한 모델이 다른 설정으로 풀리고, 결과는 오류 없이
    그럴듯하게 나온다. 한 자리에서 정해 **덱 · 요약 · 결과가 같은 것을 말하게** 한다.
    """

    low: float
    high: float
    intervals: int
    damping_ratio: float
    source: str


def harmonic_plan(spec: HarmonicSpec, given: condition_model.Conditions) -> HarmonicPlan:
    """스펙과 CAD 조건을 합쳐 실제로 풀 설정을 낸다."""
    declared = given.analysis
    low, high = spec.frequency_range_hz
    intervals, damping = spec.intervals, spec.damping_ratio
    from_cad: list[str] = []
    if declared.frequency_range is not None:
        low, high = declared.frequency_range
        from_cad.append("범위")
    if declared.intervals:
        intervals = declared.intervals
        from_cad.append("점 수")
    if declared.damping_ratio is not None:
        damping = declared.damping_ratio
        from_cad.append("감쇠비")
    if from_cad:
        logger.info("조화 설정 ← CAD: %s", " · ".join(from_cad))
    return HarmonicPlan(
        low=low,
        high=high,
        intervals=intervals,
        damping_ratio=damping,
        source="cad" if from_cad else "spec",
    )
