"""모드 잇기 — MAC(Modal Assurance Criterion).

    MAC(a, b) = |a·b|² / ((a·a)(b·b))

두 모드 형상이 같은 모양이면 1, 직교하면 0 이다. **절댓값**을 쓰는 이유: 모드 형상의 부호는
뜻이 없다(위로 휘든 아래로 휘든 같은 모드다).

지문은 정규화 격자에서 뽑은 변위다(`core/dpf/signature.py`) — 설계점마다 메시가 달라 절점끼리
곧바로 견줄 수 없기 때문이다.

## 잇지 못하면 잇지 않는다

닮은 모드가 없으면(MAC 이 낮으면) **그 자리는 비운다.** 억지로 이으면 「2차 대 두께」 그래프가
서로 다른 모드를 이은 선이 되고, 그것은 없는 그림보다 나쁘다 — 사람이 그것을 믿고 두께를
정한다.
"""

from __future__ import annotations

from dataclasses import dataclass

#: 이보다 낮으면 같은 모드로 보지 않는다. 형상이 조금 변하는 DOE 에서 같은 모드는 대개 0.8 을
#: 넘고, 다른 모드는 0.3 아래로 떨어진다. 그 사이는 **모르는 것으로 둔다.**
MATCH_ABOVE = 0.6


@dataclass(frozen=True)
class ModeLink:
    """기준 모드 하나가 어느 모드에 이어졌나."""

    reference: int
    """기준 설계점에서의 모드 번호."""
    number: int | None
    """이 설계점에서의 모드 번호. 못 이으면 None."""
    confidence: float
    """MAC 값(0~1). 못 이었으면 가장 높았던 값 — 「얼마나 아쉬웠나」 가 다음 할 일을 가른다."""


def mac(first: list[float], second: list[float]) -> float:
    """두 지문의 MAC.

    길이가 다르거나 비었으면 0 — **짐작하지 않는다.**
    """
    if not first or not second or len(first) != len(second):
        return 0.0
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    left = sum(a * a for a in first)
    right = sum(b * b for b in second)
    if left <= 0 or right <= 0:
        return 0.0
    return round((dot * dot) / (left * right), 4)


def track_modes(
    reference: list[list[float]],
    candidate: list[list[float]],
    *,
    threshold: float = MATCH_ABOVE,
) -> list[ModeLink]:
    """기준 설계점의 모드마다 이 설계점의 어느 모드가 같은 모양인지.

    **한 모드는 한 번만 쓰인다.** 두 기준 모드가 같은 후보를 가리키면 MAC 이 높은 쪽이
    가져가고, 진 쪽은 다음으로 닮은 것을 찾는다 — 안 그러면 한 모드가 둘로 갈라져 그래프에
    두 번 선다.
    """
    scores: list[tuple[float, int, int]] = []
    for ref_index, ref in enumerate(reference):
        for index, one in enumerate(candidate):
            scores.append((mac(ref, one), ref_index, index))
    scores.sort(reverse=True)

    taken_reference: dict[int, tuple[int, float]] = {}
    taken_candidate: set[int] = set()
    for value, ref_index, index in scores:
        if value < threshold:
            break
        if ref_index in taken_reference or index in taken_candidate:
            continue
        taken_reference[ref_index] = (index, value)
        taken_candidate.add(index)

    links: list[ModeLink] = []
    for ref_index in range(len(reference)):
        if ref_index in taken_reference:
            index, value = taken_reference[ref_index]
            links.append(ModeLink(reference=ref_index + 1, number=index + 1, confidence=value))
            continue
        # 못 이었다 — **가장 높았던 값을 적어 둔다.** 0.55 와 0.05 는 다음 할 일이 다르다.
        best = max(
            (mac(reference[ref_index], one) for one in candidate),
            default=0.0,
        )
        links.append(ModeLink(reference=ref_index + 1, number=None, confidence=best))
    return links
