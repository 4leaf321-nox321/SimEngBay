"""`boundary.json` — 모델링이 뒤 단계(결과 추출)에 남기는 한 장. **무엇으로 풀었나.**

추출은 스펙을 받지만, 스펙과 실제로 풀린 것이 다를 수 있다 — CAD 가 감쇠비를 적어 보내면
그것이 스펙을 이기고, CAD 가 파트마다 물성을 보내면 스펙의 물성은 쓰이지 않는다. 그때 결과에
스펙 값을 적으면 **화면이 거짓말을 한다.** 그래서 모델링이 쓴 값을 여기 남기고 추출이 읽는다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.spec import HarmonicSpec, ModalSpec, StaticSpec

logger = logging.getLogger(__name__)

BOUNDARY_NAME = "boundary.json"


def read(workdir: Path) -> dict[str, Any]:
    """파일이 없거나(옛 작업) 못 읽으면 빈 것 — 부르는 쪽이 스펙으로 본다."""
    path = workdir / BOUNDARY_NAME
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("%s 를 읽지 못했습니다 — 스펙으로 봅니다", BOUNDARY_NAME)
        return {}
    return loaded if isinstance(loaded, dict) else {}


def used_material(workdir: Path, spec: ModalSpec | StaticSpec | HarmonicSpec) -> str | None:
    """결과에 적을 물성 이름 — **모델링이 실제로 붙인 것**. 남긴 것이 없으면 스펙의 것."""
    named = read(workdir).get("material")
    if isinstance(named, str) and named:
        return named
    return spec.material.name if spec.material is not None else None
