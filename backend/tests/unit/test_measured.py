"""실측과 맞추기 — **같은 자리에서, 억지로 짝짓지 않고, 차이를 변수로 설명하는가.**"""

from __future__ import annotations

import math
from typing import Any

import pytest

from app.core.measured import compare, parse


def _rows(table: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows, errors = parse(table)
    assert not errors, errors
    return rows


def test_한글_열_이름과_단위를_기준_단위로_읽는다() -> None:
    rows = _rows(
        [
            {
                "측정점": "",
                "종류": "공진",
                "주파수": "1,250.3",
                "값": "",
                "단위": "",
                "성분": "",
            },
            {
                "측정점": "A",
                "종류": "FRF",
                "주파수": "1000",
                "값": "2",
                "단위": "g",
                "성분": "x",
            },
            {
                "측정점": "A",
                "종류": "변위",
                "주파수": "",
                "값": "40",
                "단위": "um",
                "성분": "x",
            },
            {
                "측정점": "A",
                "종류": "변형률",
                "주파수": "",
                "값": "-120",
                "단위": "ue",
                "성분": "z",
            },
        ]
    )
    assert rows[0] == {"kind": "frequency", "probe": None, "unit": "", "frequency_hz": 1250.3}
    assert rows[1]["quantity"] == "acceleration"
    assert rows[1]["value"] == pytest.approx(2 * 9806.65)  # mm/s²
    assert rows[2]["value"] == pytest.approx(0.04)  # mm
    assert rows[3]["value"] == pytest.approx(-120e-6)


def test_영어_열_이름도_받는다() -> None:
    rows = _rows([{"Probe": "A", "Kind": "displacement", "Value": "0.1", "Unit": "mm"}])
    assert rows[0]["component"] == "magnitude"


def test_틀린_줄이_하나라도_있으면_아무것도_쓰지_않는다() -> None:
    """**반쯤 들어간 실측은 그럴듯하게 틀린 비교를 낸다** — 몇 줄 빠진 FRF 는 봉우리가 옮겨
    간다."""
    rows, errors = parse(
        [
            {"측정점": "A", "종류": "공진", "주파수": "1250"},
            {"측정점": "A", "종류": "가속", "주파수": "1300"},
            {"측정점": "A", "종류": "변형률", "값": "10", "성분": "크기"},
        ]
    )
    assert rows == []
    assert any("3줄" in one and "모르는 종류" in one for one in errors)
    assert any("4줄" in one and "게이지 방향" in one for one in errors)


MODAL: dict[str, Any] = {
    "recipe": "modal",
    "modes": [
        {"number": 1, "elastic_number": 1, "frequency_hz": 1200.0, "rigid_body": False},
        {"number": 2, "elastic_number": 2, "frequency_hz": 3400.0, "rigid_body": False},
        {"number": 3, "elastic_number": 3, "frequency_hz": 3500.0, "rigid_body": False},
    ],
    # 센서 자리에서 2번 모드는 거의 안 움직인다(1%).
    "probes": [
        {"name": "A", "mode": 1, "value": 400.0},
        {"name": "A", "mode": 2, "value": 4.0},
        {"name": "A", "mode": 3, "value": 300.0},
    ],
}


def test_센서_자리에서_안_움직이는_모드와는_짝을_짓지_않는다() -> None:
    """3,450 Hz 는 주파수로는 3,400 Hz(2번)가 더 가깝지만, 그 모드는 센서 자리에서 1% 만
    움직인다 — 그 센서로는 안 보였을 모드다. 3,500 Hz(3번)와 짓는다."""
    rows = _rows([{"측정점": "A", "종류": "공진", "주파수": "3450"}])
    found = compare(MODAL, rows)["frequency"]
    match = found["matches"][0]
    assert match["mode"] == 3
    assert match["diff_pct"] == pytest.approx((3500 - 3450) / 3450 * 100)
    assert match["visibility"] == pytest.approx(0.75)


def test_측정점이_없는_공진은_모든_모드에서_찾는다() -> None:
    rows = _rows([{"종류": "공진", "주파수": "3450"}])
    match = compare(MODAL, rows)["frequency"]["matches"][0]
    assert match["mode"] == 2
    # 3,400 · 3,500 이 둘 다 10% 안 — 짝이 확실하지 않다.
    assert match["ambiguous"] is True


def test_한_모드에_한_번만_짝을_짓고_창_밖은_짓지_않는다() -> None:
    rows = _rows(
        [
            {"종류": "공진", "주파수": "1190"},
            {"종류": "공진", "주파수": "1210"},
            {"종류": "공진", "주파수": "9000"},
        ]
    )
    matches = compare(MODAL, rows)["frequency"]["matches"]
    assert [one["mode"] for one in matches].count(1) == 1
    assert matches[2]["mode"] is None, "±25% 밖은 짝을 짓지 않는다"


def test_모든_모드가_같은_비율로_어긋나면_영률로_설명한다() -> None:
    """f ∝ √E — 실측이 모든 모드에서 √(195/200) 배면 영률 195 GPa 를 제안한다."""
    ratio = math.sqrt(195 / 200)
    rows = _rows(
        [
            {"측정점": "A", "종류": "공진", "주파수": str(1200 * ratio)},
            {"측정점": "A", "종류": "공진", "주파수": str(3500 * ratio)},
        ]
    )
    found = compare(MODAL, rows, youngs_gpa=200)["frequency"]
    assert found["suggested_modulus_gpa"] == pytest.approx(195, rel=1e-6)
    assert "195.0 GPa" in found["explanation"]


def test_모드마다_비율이_다르면_물성을_제안하지_않는다() -> None:
    rows = _rows(
        [
            {"측정점": "A", "종류": "공진", "주파수": "1150"},
            {"측정점": "A", "종류": "공진", "주파수": "3600"},
        ]
    )
    found = compare(MODAL, rows, youngs_gpa=200)["frequency"]
    assert found["suggested_modulus_gpa"] is None
    assert "물성 하나로는 설명되지" in found["explanation"]


def _sdof(frequency: float, natural: float, zeta: float) -> float:
    ratio = frequency / natural
    return 1.0 / math.sqrt((1 - ratio**2) ** 2 + (2 * zeta * ratio) ** 2)


def test_FRF_의_봉우리와_감쇠를_견주고_감쇠비를_제안한다() -> None:
    """실측은 가속도(g) · 감쇠 3% · 1,000 Hz, 해석은 변위(mm) · 감쇠 2% · 1,020 Hz.

    해석 변위를 (2πf)² 로 가속도로 옮겨 견준다. 반전력 대역이 실측 감쇠 3% 를 되찾고, 높이 비가
    「감쇠를 올려라」 를 말한다."""
    freqs = [900 + index * 0.5 for index in range(401)]
    measured = [
        {
            "측정점": "A",
            "종류": "FRF",
            "주파수": str(f),
            "값": str(_sdof(f, 1000, 0.03)),
            "단위": "g",
        }
        for f in freqs
    ]
    # 해석 진폭(mm) — 가속도로 옮겼을 때 실측과 같은 크기가 되도록 맞춘 뒤 감쇠만 다르게.
    scale = 9806.65 / (2 * math.pi * 1000) ** 2
    result = {
        "recipe": "harmonic",
        "units": {"displacement": "mm"},
        "damping_ratio": 0.02,
        "points": [
            {
                "frequency_hz": f,
                "max_displacement": 1.0,
                "probes": {"A": scale * _sdof(f, 1020, 0.02)},
            }
            for f in freqs
        ],
    }
    found = compare(result, _rows(measured))["frf"][0]
    assert found["quantity"] == "acceleration"
    assert found["measured_peak_hz"] == pytest.approx(1000, abs=1)
    assert found["peak_diff_pct"] == pytest.approx(2.0, abs=0.2)
    assert found["measured_damping"] == pytest.approx(0.03, rel=0.05)
    assert found["amplitude_ratio"] > 1.3, "감쇠가 작으면 봉우리가 높다"
    assert found["suggested_damping"] > 0.02
    assert len(found["measured"]) <= 401


def test_가진력으로_나눈_FRF_는_높이를_견주지_않는다() -> None:
    rows = _rows([{"측정점": "A", "종류": "FRF", "주파수": "1000", "값": "1", "단위": "g/N"}])
    result = {
        "recipe": "harmonic",
        "units": {"displacement": "mm"},
        "damping_ratio": 0.02,
        "points": [{"frequency_hz": 1000, "max_displacement": 1, "probes": {"A": 0.1}}],
    }
    found = compare(result, rows)["frf"][0]
    assert found["amplitude_ratio"] is None
    assert "위치만" in found["note"]


STATIC: dict[str, Any] = {
    "recipe": "static",
    "probes": [
        {
            "name": "A",
            "value": 0.05,
            "unit": "mm",
            "vector": [0.04, 0.0, -0.03],
            "strain": [1e-4, -3e-5, -2e-4],
        }
    ],
}


def test_정적_변위_성분과_변형률을_같은_자리에서_견준다() -> None:
    rows = _rows(
        [
            {"측정점": "A", "종류": "변위", "값": "0.041", "단위": "mm", "성분": "x"},
            {"측정점": "A", "종류": "변위", "값": "50", "단위": "um", "성분": "크기"},
            {"측정점": "A", "종류": "변형률", "값": "-210", "단위": "ue", "성분": "z"},
        ]
    )
    found = compare(STATIC, rows, youngs_gpa=200)["static"]
    by = {(one["kind"], one["component"]): one for one in found["matches"]}
    assert by[("displacement", "x")]["diff_pct"] == pytest.approx((0.04 - 0.041) / 0.041 * 100)
    assert by[("displacement", "magnitude")]["diff_pct"] == pytest.approx(0.0, abs=1e-9)
    assert by[("strain", "z")]["analysis"] == pytest.approx(-2e-4)


def test_변위로_당긴_모델은_영률로_설명하지_않는다() -> None:
    rows = _rows(
        [{"측정점": "A", "종류": "변위", "값": "0.025", "단위": "mm", "성분": "크기"}]
    )
    forced = compare(STATIC, rows, youngs_gpa=200, force_driven=True)["static"]
    assert forced["suggested_modulus_gpa"] == pytest.approx(400)
    pulled = compare(STATIC, rows, youngs_gpa=200, force_driven=False)["static"]
    assert pulled["suggested_modulus_gpa"] is None
    assert "변위로 당긴" in pulled["explanation"]


def test_레시피가_다르면_까닭을_적고_넘긴다() -> None:
    rows = _rows([{"측정점": "A", "종류": "FRF", "주파수": "1000", "값": "1", "단위": "mm"}])
    found = compare(MODAL, rows)
    assert found["frf"] == []
    assert any("조화 응답" in one for one in found["skipped"])
    assert found["score_pct"] is None


def test_점수는_차이의_절댓값_평균이다() -> None:
    rows = _rows([{"측정점": "A", "종류": "공진", "주파수": "1250"}])
    found = compare(MODAL, rows)
    assert found["score_pct"] == pytest.approx(abs((1200 - 1250) / 1250 * 100))
