"""메시 수렴 점검 — **같은 설계점을 요소 크기만 바꿔 풀고, 값이 자리를 잡았나를 판정한다.**

모의 실행기는 요소 크기에 따라 절점 수와 값을 움직인다(성긴 메시는 뻣뻣하다 — 주파수는 높게,
변형은 작게). 판정 자체(GCI)는 `tests/unit/test_convergence.py` 가 지키고, 여기서는 묶음이
제대로 만들어지고 읽히는지를 본다.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from tests.api.conftest import Signed

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
SHEAR_POINT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_전단이음"
    / "points"
    / "p0002.json"
)


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


def _create(
    client: TestClient, who: Signed, spec: dict[str, Any], topology: bytes | None = None
) -> dict[str, Any]:
    files: dict[str, Any] = {"file": ("시편.step", io.BytesIO(STEP), "model/step")}
    if topology is not None:
        files["topology"] = ("topology.json", io.BytesIO(topology), "application/json")
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files=files,
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_크기를_줄여_다시_풀고_1차_주파수의_수렴을_판정한다(
    client: TestClient, member: Signed
) -> None:
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 5}},
    )
    assert original["status"] == "done"
    # 모델링이 **실제로 쓴 크기**를 적는다 — 줄일 크기를 이것으로 제안한다.
    assert original["summary"]["element_size_mm"] == 5

    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [3.5, 2.5]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["base_size_mm"] == 5
    levels = body["levels"]
    assert [one["element_size_mm"] for one in levels] == [5, 3.5, 2.5], "성긴 것부터"
    assert levels[0]["is_original"] is True
    nodes = [one["nodes"] for one in levels]
    assert nodes == sorted(nodes) and len(set(nodes)) == 3, "줄일수록 절점이 는다"

    first = next(one for one in body["metrics"] if one["key"] == "first_elastic_hz")
    values = first["values"]
    assert values[0] > values[1] > values[2], "성긴 메시는 뻣뻣하다 — 주파수가 높다"
    assert first["order"] == pytest.approx(2.0, rel=0.15)
    assert first["status"] == "converged"
    assert first["gci_pct"] < 1.0

    # **수준 작업으로 물어도 같은 묶음**이다.
    level_id = levels[2]["simulation_id"]
    again = client.get(f"/api/simulations/{level_id}/convergence", headers=member.headers)
    assert again.status_code == 200
    assert again.json()["original_id"] == original["id"]


def test_첨두응력이_정련할수록_커지면_발산이라고_말한다(
    client: TestClient, member: Signed
) -> None:
    """**고장이 아니라 수렴할 수 없는 값이다** — 측정점 · 변형으로 판단하라고 적는다."""
    original = _create(
        client,
        member,
        {"recipe": "static", "material": MATERIAL, "mesh": {"element_size_mm": 5}},
        topology=SHEAR_POINT.read_bytes(),
    )
    assert original["status"] == "done", original
    body = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [3.5, 2.5]},
        headers=member.headers,
    ).json()
    stress = next(one for one in body["metrics"] if one["key"] == "max_mpa")
    assert stress["status"] == "diverging"
    assert "특이점" in stress["note"]
    keys = {one["key"] for one in body["metrics"]}
    # 실측과 견줄 값(반력 · 측정점)도 판정한다.
    assert "reaction:당기는 끝" in keys
    assert "probe:이음 입구 위판" in keys


def test_끝나지_않은_작업은_점검하지_않는다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    waiting = _create(client, member, {"recipe": "modal", "material": MATERIAL})
    got = client.post(
        f"/api/simulations/{waiting['id']}/convergence",
        json={"sizes_mm": [2.0]},
        headers=member.headers,
    )
    assert got.status_code == 409
    assert got.json()["error"]["details"]["status"] == "queued"


def test_수준은_다섯까지다(client: TestClient, member: Signed) -> None:
    """**그 너머는 정련보다 다른 원인을 볼 때다** — 수렴하지 않는 값을 메시로만 쫓지 않는다."""
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 4}},
    )
    got = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [3.0, 2.5, 2.0, 1.5]},
        headers=member.headers,
    )
    assert got.status_code == 201
    more = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [1.0]},
        headers=member.headers,
    )
    assert more.status_code == 400


def test_다른_솔버로_점검하면_원래_크기도_그_솔버로_푼다(
    client: TestClient, member: Signed
) -> None:
    """**판정은 한 솔버의 수준끼리만** — 두 솔버의 차이(몇 %)가 메시 차이로 읽히면 안 된다.
    CalculiX 로 점검하면 Ansys 라이선스를 쓰지 않는다."""
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 5}},
    )
    body = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [3.5, 2.5], "solver": "calculix"},
        headers=member.headers,
    ).json()
    assert {one["solver"] for one in body["levels"]} == {"calculix"}
    assert [one["element_size_mm"] for one in body["levels"]] == [5, 3.5, 2.5]
    assert any("솔버가 섞여" in one for one in body["notes"])

    # 같은 크기를 다시 달라면 만들지 않는다.
    again = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [2.5], "solver": "calculix"},
        headers=member.headers,
    )
    assert again.status_code == 400
