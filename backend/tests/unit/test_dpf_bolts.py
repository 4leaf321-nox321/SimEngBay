"""Ansys 추출의 볼트 힘 — **반력이 없는 볼트를 언제 준 예압으로 채우나**(2026-11-28 검토).

예압 절점에 반력이 없는 까닭은 둘이다. (가) 힘으로 조이는 단계(Load) — 절점이 묶이지 않는다,
볼트 힘은 준 예압이다. (나) 아직 안 조인 단계(Open) — 볼트에 힘이 없다. (나)를 (가)로 보면 뒤
케이스에서 조이는 볼트가 앞 케이스에서 「1000 N (준 예압)」 으로 보인다(v0.37.0 의 사슬에서
생긴 회귀). DPF 는 이 기계에 없다 — 결과 파일은 세트마다 절점 값을 돌려주는 가짜다. 끝까지
도는 것은 `tests/ansys/test_cases_ansys.py` · `test_nonlinear_static_ansys.py` 가 본다.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import cases
from app.core.dpf import probes
from app.core.dpf import static as dpf_static

DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"
#: 볼트 예압 절점 — PRETS179 의 마지막 절점(볼트를 만든 차례).
FIRST, SECOND = 900, 901

Sets = dict[int, dict[int, list[float]]]


class _Result:
    """세트 번호 → {절점: 값} — DPF 결과의 `on_time_scoping([세트]).eval()[0]` 모양."""

    def __init__(self, by_set: Sets) -> None:
        self.by_set = by_set

    def on_time_scoping(self, sets: list[int]) -> Any:
        [one] = sets
        rows = self.by_set.get(one, {})
        field = SimpleNamespace(
            data=[value for value in rows.values()], scoping=SimpleNamespace(ids=list(rows))
        )
        return SimpleNamespace(eval=lambda: [field])


def _model(times: list[float], reactions: Sets) -> Any:
    moved: Sets = {
        index: {FIRST: [0.001 * index, 0, 0], SECOND: [0.002 * index, 0, 0]}
        for index in range(1, len(times) + 1)
    }
    return SimpleNamespace(
        metadata=SimpleNamespace(
            time_freq_support=SimpleNamespace(
                n_sets=len(times), time_frequencies=SimpleNamespace(data=times)
            )
        ),
        results=SimpleNamespace(
            reaction_force=_Result(reactions), displacement=_Result(moved)
        ),
    )


def _mesh(bolts: int) -> Any:
    nodes = {10: [1, 2, FIRST], 11: [3, 4, SECOND], 12: [5, 6, 7]}
    kinds = [179, 179, 187] if bolts == 2 else [179, 187, 187]
    return SimpleNamespace(
        property_field=lambda name: SimpleNamespace(data=kinds),
        elements=SimpleNamespace(
            scoping=SimpleNamespace(ids=list(nodes)),
            element_by_id=lambda one: SimpleNamespace(node_ids=nodes[one]),
        ),
    )


def _topology(bolts: int) -> dict[str, Any]:
    """「조건_볼트예압_단계둘」 의 조건 — 볼트 예압 1000 N(둘이면 같은 몸통에 하나 더)."""
    payload = json.loads(
        (DOE / "조건_볼트예압_단계둘" / "points" / "p0001.json").read_text(encoding="utf-8")
    )
    if bolts == 2:
        loads = payload["conditions"]["cases"][0]["loads"]
        bolt = next(one for one in loads if one["type"] == "bolt_pretension")
        loads.append({**copy.deepcopy(bolt), "name": "볼트 둘"})
    found, broken = cases.chains(payload)
    assert not broken
    [chain] = found
    view: dict[str, Any] = cases.view(payload, chain)
    return view


@pytest.fixture(autouse=True)
def _only_bolts(monkeypatch: pytest.MonkeyPatch) -> None:
    """케이스 행의 다른 값(변위 · 응력 · 반력)은 이 시험의 몫이 아니다."""
    monkeypatch.setattr(probes, "at_set", lambda result, step: None)
    monkeypatch.setattr(dpf_static, "_body_nodes", lambda mesh: None)
    monkeypatch.setattr(dpf_static, "_peak", lambda field, nodes=None: (0.0, "mm"))
    monkeypatch.setattr(dpf_static, "_von_mises", lambda model, step=None: (None, ""))
    monkeypatch.setattr(dpf_static, "_plastic", lambda model, step=None: None)
    monkeypatch.setattr(dpf_static, "_peak_components", lambda field, nodes: [0.0, 0.0, 0.0])
    monkeypatch.setattr(dpf_static, "_reactions", lambda *args: {})


def _boundary(workdir: Path, **rows: Any) -> None:
    (workdir / "boundary.json").write_text(json.dumps(rows, ensure_ascii=False), "utf-8")


def _bolts(found: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [one["bolts"] for one in found]


def test_뒤_케이스에서_조이는_볼트는_앞_케이스에서_힘이_없다(tmp_path: Path) -> None:
    """「중력」(볼트 Open) → 「중력 + 볼트」(조임 → 잠금) — 앞 케이스 끝은 반력이 없어도 준
    예압이 아니다(`None`). 뒤 케이스 끝은 잠근 단계의 반력이다."""
    _boundary(
        tmp_path,
        cases=[
            {"name": "중력", "step": 1, "tightened": None},
            {"name": "중력 + 볼트", "step": 3, "tightened": 2},
        ],
    )
    model = _model([1.0, 2.0, 3.0], {3: {FIRST: [1000.5, 0, 0]}})
    resting, tightened = _bolts(
        dpf_static._cases(model, _mesh(1), _topology(1), tmp_path, "mm")
    )
    assert resting["볼트 예압"]["force_n"] is None
    assert "force_given" not in resting["볼트 예압"]
    assert tightened["볼트 예압"]["force_n"] == pytest.approx(1000.5)
    assert "force_given" not in tightened["볼트 예압"]


def test_케이스마다_다른_볼트를_조이면_안_조인_볼트는_힘이_없다(tmp_path: Path) -> None:
    """「가」 가 첫 볼트를, 「나」 가 둘째 볼트를 조인다 — 「가」 끝(잠근 단계)의 둘째 볼트는
    아직 Open 이다. 「조인 단계 뒤면 채운다」 로 두면 여기서 준 예압이 된다."""
    _boundary(
        tmp_path,
        cases=[
            {"name": "가", "step": 2, "tightened": 1},
            {"name": "나", "step": 4, "tightened": 3},
        ],
    )
    model = _model(
        [1.0, 2.0, 3.0, 4.0],
        {
            2: {FIRST: [1001.0, 0, 0]},
            3: {FIRST: [1002.0, 0, 0]},
            4: {FIRST: [1003.0, 0, 0], SECOND: [998.0, 0, 0]},
        },
    )
    first, second = _bolts(dpf_static._cases(model, _mesh(2), _topology(2), tmp_path, "mm"))
    assert first["볼트 예압"]["force_n"] == pytest.approx(1001.0)
    assert first["볼트 둘"]["force_n"] is None and "force_given" not in first["볼트 둘"]
    assert second["볼트 예압"]["force_n"] == pytest.approx(1003.0)
    assert second["볼트 둘"]["force_n"] == pytest.approx(998.0)


def test_하중_단계의_첫_단계_끝은_준_예압이고_끝_시각을_따른다(tmp_path: Path) -> None:
    """하중 단계(CompCore ②)의 볼트는 첫 단계에서 힘으로 조인다 — 그 단계 끝은 반력이 없어 준
    예압이다(`force_given`). 첫 단계의 끝 시각이 1 이 아니어도(0.5) 그 시각의 세트다 — 시각
    1.0 으로 찾으면 둘째 단계 끝의 세트를 집는다."""
    _boundary(
        tmp_path,
        steps=[
            {"name": "예압", "step": 1, "time": 0.5},
            {"name": "외력", "step": 2, "time": 1.0},
        ],
    )
    model = _model(
        [0.25, 0.5, 0.75, 1.0], {3: {FIRST: [1040.0, 0, 0]}, 4: {FIRST: [1066.2, 0, 0]}}
    )
    loaded, pulled = _bolts(
        dpf_static._cases(model, _mesh(1), _topology(1), tmp_path, "mm", key="steps")
    )
    assert loaded["볼트 예압"]["force_n"] == pytest.approx(1000.0)
    assert loaded["볼트 예압"]["force_given"] is True
    assert pulled["볼트 예압"]["force_n"] == pytest.approx(1066.2)
    assert "force_given" not in pulled["볼트 예압"]
    assert dpf_static._loading_set(model, tmp_path) == 2

    # 맨 위의 값은 끝(잠근 단계)이다 — 준 예압이 아니다.
    top = dpf_static._bolts(
        model,
        _mesh(1),
        _topology(1),
        "mm",
        first_set=dpf_static._loading_set(model, tmp_path),
    )
    assert top["볼트 예압"]["force_n"] == pytest.approx(1066.2)


def test_단계가_하나인_하중_단계는_끝이_곧_조이는_단계다(tmp_path: Path) -> None:
    _boundary(tmp_path, steps=[{"name": "예압", "step": 1, "time": 1.0}])
    model = _model([0.5, 1.0], {})
    top = dpf_static._bolts(
        model,
        _mesh(1),
        _topology(1),
        "mm",
        first_set=dpf_static._loading_set(model, tmp_path),
    )
    assert top["볼트 예압"]["force_n"] == pytest.approx(1000.0)
    assert top["볼트 예압"]["force_given"] is True


def test_하중_단계가_없으면_반력_없는_볼트는_힘이_없다(tmp_path: Path) -> None:
    """v1 볼트 정적은 끝이 잠근 단계라 반력이 있다 — 없으면 v0.37.0 처럼 `None`."""
    model = _model([1.0, 2.0], {})
    assert dpf_static._loading_set(model, tmp_path) is None
    top = dpf_static._bolts(model, _mesh(1), _topology(1), "mm", first_set=None)
    assert top["볼트 예압"]["force_n"] is None
    assert "force_given" not in top["볼트 예압"]
