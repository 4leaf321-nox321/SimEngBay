"""Ansys 정적의 변형 그림은 **수와 같은 결과 단계**를 그린다(2026-10-24).

수(최대 변형 · 응력 · 반력)는 DPF 의 기본인 마지막 단계를 읽는데, 그림은 1 로 박혀 있었다 —
비선형 정적(큰 변형 · 마찰 · 부단계)에서는 결과 파일에 부단계마다 단계가 남아, 그림이 **첫
부단계의 모양**을 그렸다. DPF 없이 가짜 모델로 어느 단계를 묻는지만 본다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.dpf import shapes
from app.core.dpf import static as dpf_static


def _model(sets: int) -> Any:
    return SimpleNamespace(
        metadata=SimpleNamespace(time_freq_support=SimpleNamespace(n_sets=sets))
    )


@pytest.mark.parametrize("sets", [1, 20])
def test_마지막_단계를_그리고_어느_단계인지_적는다(
    sets: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: dict[str, Any] = {}

    def export(
        model: Any, skin: Any, mode: int, workdir: Path, **options: Any
    ) -> dict[str, Any]:
        asked.update(mode=mode, **options)
        return {"vtp": "mode_01.vtp", "points": 10, "max_displacement": 4.2}

    monkeypatch.setattr(shapes, "skin_of", lambda mesh: mesh)
    monkeypatch.setattr(shapes, "export_mode", export)
    result: dict[str, Any] = {}
    made = dpf_static._draw(_model(sets), object(), tmp_path, result)

    # 파일 이름(mode_01)은 그대로, 변위는 마지막 단계에서.
    assert asked == {"mode": 1, "result_set": sets}
    assert result["shape"]["set"] == sets
    assert result["shape"]["max_displacement"] == 4.2
    assert [one.kind for one in made] == ["mode_vtp"]
