"""Ansys 정적 추출의 **최대 등가 소성 변형률** — 「항복하지 않았다(0)」 와 「못 읽었다
(모름)」 를 가른다(가짜 DPF, Ansys 없이).

CalculiX 는 소성 재료면 PE 블록을 늘 써서 항복하지 않아도 0 을 적는다. Ansys 는 EPPL 이 모두
0 이면 칸을 비웠다 — 그러면 DOE 의 「소성 변형률 ≤ …」 조건에서 항복하지 않은 두꺼운
설계점이 빠진다. 그렇다고 못 읽은 것까지 0 으로 적으면 **위험한 설계점이 가장 좋은 후보로
올라간다.** 그래서 모델링이 「소성으로 풀었다」 를 `boundary.json` 에 남기고(`plastic`),
추출이 그것을 보고 가른다:

- 소성 · 모두 0 → 0.0, 소성 · 읽기 실패 → None(결과에 알림), 탄성 → None.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from app.core.dpf import static
from app.core.mechanical.build import _write_boundary
from app.core.spec import parse_spec


class _Data:
    def __init__(self, values: list[float]) -> None:
        self._values = values

    def ravel(self) -> list[float]:
        return self._values


class _Field:
    def __init__(self, values: list[float]) -> None:
        self.data = _Data(values)


def _dpf(monkeypatch: pytest.MonkeyPatch, values: list[float] | None) -> None:
    """`ansys.dpf.core.operators.result.plastic_strain_eqv` 만 있는 가짜 — `None` 이면
    못 읽는다."""

    class _Operator:
        def __init__(self, **_given: Any) -> None:
            pass

        def eval(self) -> list[_Field]:
            if values is None:
                raise RuntimeError("EPPL 이 결과에 없습니다")
            return [_Field(values)]

    core = types.ModuleType("ansys.dpf.core")
    core.operators = types.SimpleNamespace(  # type: ignore[attr-defined]
        result=types.SimpleNamespace(plastic_strain_eqv=_Operator)
    )
    dpf = types.ModuleType("ansys.dpf")
    dpf.core = core  # type: ignore[attr-defined]
    ansys = types.ModuleType("ansys")
    ansys.dpf = dpf  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ansys", ansys)
    monkeypatch.setitem(sys.modules, "ansys.dpf", dpf)
    monkeypatch.setitem(sys.modules, "ansys.dpf.core", core)


MODEL = types.SimpleNamespace(metadata=types.SimpleNamespace(data_sources=None))


def test_소성으로_풀었고_모두_0_이면_0_이다(monkeypatch: pytest.MonkeyPatch) -> None:
    _dpf(monkeypatch, [0.0, 0.0, 0.0])
    assert static._plastic(MODEL, plastic=True) == 0.0
    # 탄성 재료면 같은 0 들이라도 비운다 — 소성 변형률이 없는 해석이다.
    assert static._plastic(MODEL, plastic=False) is None


def test_항복했으면_최대를_적는다(monkeypatch: pytest.MonkeyPatch) -> None:
    _dpf(monkeypatch, [0.0, 0.0021, 0.0148535])
    assert static._plastic(MODEL, plastic=True) == 0.0148535


def test_못_읽었으면_0_이_아니라_모름이다(monkeypatch: pytest.MonkeyPatch) -> None:
    _dpf(monkeypatch, None)
    assert static._plastic(MODEL, plastic=True) is None
    _dpf(monkeypatch, [])
    assert static._plastic(MODEL, plastic=True) is None
    assert "읽지 못했습니다" in static.UNREAD_PLASTIC
    assert "0 으로 적지 않습니다" in static.UNREAD_PLASTIC


def test_모델링이_소성으로_풀었다고_남긴다(tmp_path: Path) -> None:
    spec = parse_spec({"recipe": "static"})
    _write_boundary(tmp_path, constrained=True, spec=spec, plastic=True)
    assert (
        json.loads((tmp_path / "boundary.json").read_text(encoding="utf-8"))["plastic"] is True
    )
    _write_boundary(tmp_path, constrained=True, spec=spec)
    assert "plastic" not in json.loads(
        (tmp_path / "boundary.json").read_text(encoding="utf-8")
    )
