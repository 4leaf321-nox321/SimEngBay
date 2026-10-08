"""메시 수렴 점검 — **같은 설계점을 요소 크기만 바꿔 풀고, 값이 자리를 잡았나를 판정한다.**

모의 실행기는 요소 크기에 따라 절점 수와 값을 움직인다(성긴 메시는 뻣뻣하다 — 주파수는 높게,
변형은 작게). 판정 자체(GCI)는 `tests/unit/test_convergence.py` 가 지키고, 여기서는 묶음이
제대로 만들어지고 읽히는지를 본다.
"""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
SIDE_POINT = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_측면가진"
    / "points"
    / "p0001.json"
)
SHELL_POINTS = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "doe"
    / "조건_강체지그_쉘브래킷"
    / "points"
)
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
        {
            "recipe": "modal",
            "solver": "ansys",
            "material": MATERIAL,
            "mesh": {"element_size_mm": 5},
        },
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


def test_CAD_가_크기를_적은_파트와_면도_같은_비율로_줄인다(
    client: TestClient, member: Signed
) -> None:
    """**비례 정련** — 전에는 전체 크기만 줄여서 CAD 가 크기를 적은 파트 · 면은 그대로였고,
    판정에 「정련이 고르지 않습니다」 라고만 적었다. 이제 수준마다 「새 크기 / 원래 크기」 를
    스펙에 적고(`mesh.local_scale`) 모델링이 그 배율을 곱한다. 점 파일은 CAD 가 보낸
    그대로다."""
    payload = json.loads(SIDE_POINT.read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = [{"name": "기둥", "mesh": {"element_size": 1.5}}]
    payload["conditions"]["mesh_hints"].append({"on": "기둥 끝", "element_size": 0.8})
    original = _create(
        client,
        member,
        {"recipe": "modal", "mesh": {"element_size_mm": 4}},
        json.dumps(payload, ensure_ascii=False).encode(),
    )
    assert original["status"] == "done", original
    # **비율로 묻는다** — 원래 4 mm 에 0.5 · 0.25 를 곱해 2 · 1 mm, 파트 · 면도 같은 비율.
    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.5, 0.25]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert sorted(one["ratio"] for one in body["levels"]) == [0.25, 0.5, 1.0]
    scales = {}
    for level in body["levels"]:
        if level["is_original"]:
            continue
        job = client.get(f"/api/simulations/{level['simulation_id']}", headers=member.headers)
        mesh = job.json()["spec"]["mesh"]
        scales[mesh["element_size_mm"]] = mesh["local_scale"]
    assert scales == {2: 0.5, 1: 0.25}
    # 화면이 미리 보일 자리 — 파트 · 면과 그 크기(mm), 그리고 수준마다 곱한 배율.
    assert body["local_sizes"] == [
        {"name": "기둥", "kind": "part", "size_mm": 1.5},
        {"name": "기둥 끝", "kind": "face", "size_mm": 0.8},
    ]
    assert sorted(one["local_scale"] for one in body["levels"]) == [0.25, 0.5, 1.0]
    notes = body["notes"]
    assert any("같은 비율로 줄였습니다(비례 정련)" in one for one in notes), notes
    assert any("기둥" in one and "기둥 끝" in one for one in notes)


def _sized_point() -> bytes:
    """CAD 가 파트 · 면 크기를 적은 측면가진 점."""
    payload = json.loads(SIDE_POINT.read_text(encoding="utf-8"))
    payload["conditions"]["body_settings"] = [{"name": "기둥", "mesh": {"element_size": 1.5}}]
    payload["conditions"]["mesh_hints"].append({"on": "기둥 끝", "element_size": 0.8})
    return json.dumps(payload, ensure_ascii=False).encode()


def test_점검_전에는_비례_정련했다고_말하지_않는다(client: TestClient, member: Signed) -> None:
    """수준이 하나도 없으면 줄인 것도 없다 — 「같은 비율로 줄였습니다」 는 점검을 건 뒤의
    말이다. 줄일 자리(파트 · 면)는 미리 보인다 — 점검 창이 그것으로 크기를 미리 보인다."""
    original = _create(
        client, member, {"recipe": "modal", "mesh": {"element_size_mm": 4}}, _sized_point()
    )
    body = client.get(
        f"/api/simulations/{original['id']}/convergence", headers=member.headers
    ).json()
    assert [one["name"] for one in body["local_sizes"]] == ["기둥", "기둥 끝"]
    assert not any("비례 정련" in one for one in body["notes"]), body["notes"]


def test_CAD_조건을_끄고_푼_작업에는_CAD_크기를_보이지_않는다(
    client: TestClient, member: Signed
) -> None:
    """`conditions_from="spec"` 이면 빌더가 점 파일을 안 읽는다 — CAD 가 적은 파트 · 면 크기도
    안 쓴다. 보이면 쓰지도 않은 크기를 줄였다고 읽힌다."""
    original = _create(
        client,
        member,
        {
            "recipe": "modal",
            "conditions_from": "spec",
            "material": MATERIAL,
            "mesh": {"element_size_mm": 4},
        },
        _sized_point(),
    )
    assert original["status"] == "done", original
    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.5]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    assert made.json()["local_sizes"] == []
    assert not any("기둥" in one for one in made.json()["notes"])


def test_옛_방식_크기도_원래의_두_배까지다(client: TestClient, member: Signed) -> None:
    """비율과 같은 한도 — 크기에서 나온 배율이 스펙 칸의 한도를 넘어 속 칸 이름으로 거절되던
    것을, 사람이 읽을 까닭으로 먼저 막는다."""
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 5}},
    )
    refused = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [60]},
        headers=member.headers,
    )
    assert refused.status_code == 400, refused.text
    assert "2배보다 큰 크기는 점검하지 않습니다" in refused.json()["error"]["message"]


def test_비례_정련_전에_만든_수준은_같은_크기로_다시_풀어_대신한다(
    client: TestClient, member: Signed, db: Session
) -> None:
    """안내가 「새로 점검하는 크기부터는 같은 비율로」 라고 하는데 같은 크기는 「이미
    풀었다」 로 막히면 판정이 영영 고르지 않다. CAD 크기를 그대로 둔 옛 수준은 푼 크기로 치지
    않고, 비례로 다시 풀면 그 크기의 옛 수준은 판정에서 빠진다."""
    original = _create(
        client, member, {"recipe": "modal", "mesh": {"element_size_mm": 4}}, _sized_point()
    )
    first = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.5]},
        headers=member.headers,
    )
    assert first.status_code == 201, first.text
    old_id = next(one for one in first.json()["levels"] if not one["is_original"])[
        "simulation_id"
    ]
    # 비례 정련 전에 만든 수준처럼 — 배율 칸이 없다.
    row = db.get(Simulation, uuid.UUID(old_id))
    assert row is not None
    mesh = {k: v for k, v in (row.spec["mesh"]).items() if k != "local_scale"}
    row.spec = {**row.spec, "mesh": mesh}
    db.commit()
    uneven = client.get(
        f"/api/simulations/{original['id']}/convergence", headers=member.headers
    ).json()
    assert any("그대로 둔 수준이" in one for one in uneven["notes"])

    again = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.5]},
        headers=member.headers,
    )
    assert again.status_code == 201, again.text
    body = again.json()
    levels = [one for one in body["levels"] if not one["is_original"]]
    assert len(levels) == 1 and levels[0]["simulation_id"] != old_id
    assert any("같은 비율로 줄였습니다(비례 정련)" in one for one in body["notes"])


def test_비율_한도는_반올림에_흔들리지_않고_너무_촘촘한_비율은_거절한다(
    client: TestClient, member: Signed
) -> None:
    """원래 크기가 긴 소수면 비율 2 가 반올림으로 2.0000001 이 돼 거절됐다. 아래로는 0.1 —
    그보다 작으면 배율이 반올림에서 0 이 돼 속 칸 이름으로 거절됐다."""
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 3.3333333}},
    )
    assert "local_scale" not in original["spec"]["mesh"]
    coarse = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [2]},
        headers=member.headers,
    )
    assert coarse.status_code == 201, coarse.text
    fine = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.05]},
        headers=member.headers,
    )
    assert fine.status_code in (400, 422), fine.text


def test_CAD_크기가_없어도_배율은_적고_안내는_없다(client: TestClient, member: Signed) -> None:
    """**어떤 경우라도 원래 대비 비례다** — 배율은 늘 적는다(곱할 파트 · 면이 없으면 아무 일도
    안 한다). 함께 줄어든 자리가 없으니 「비례 정련」 안내는 없다."""
    original = _create(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL, "mesh": {"element_size_mm": 5}},
    )
    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"sizes_mm": [2.5]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    level = next(one for one in made.json()["levels"] if not one["is_original"])
    job = client.get(f"/api/simulations/{level['simulation_id']}", headers=member.headers)
    assert job.json()["spec"]["mesh"]["local_scale"] == 0.5
    assert not any("비례 정련" in one for one in made.json()["notes"])


def test_솔버_칸이_없는_옛_작업을_점검하면_원래_솔버로_푼다(
    client: TestClient, member: Signed, db: Session
) -> None:
    """솔버를 비우면 「원래 작업의 솔버로」 — 칸이 없는 옛 작업은 Ansys 다. 스펙을 그대로
    베끼면 새 기본값(CalculiX)으로 만들어졌다(2026-10-08)."""
    original = _create(
        client,
        member,
        {
            "recipe": "modal",
            "solver": "ansys",
            "material": MATERIAL,
            "mesh": {"element_size_mm": 5},
        },
    )
    row = db.get(Simulation, uuid.UUID(original["id"]))
    assert row is not None
    row.spec = {key: value for key, value in row.spec.items() if key != "solver"}
    db.commit()
    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.7]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    level = next(one for one in made.json()["levels"] if not one["is_original"])
    job = client.get(f"/api/simulations/{level['simulation_id']}", headers=member.headers)
    assert job.json()["spec"]["solver"] == "ansys"


def test_원래_크기를_모르면_비율을_곱할_기준이_없다고_거절한다(
    client: TestClient, member: Signed, db: Session
) -> None:
    """Ansys 를 크기 없이(Mechanical 기본값으로) 푼 작업 — 짐작한 크기로 풀면 원래보다 성기게
    풀릴 수도 있다. 비율도 mm 도 둘 다 주거나 둘 다 안 주면 스펙에서 거절한다."""
    original = _create(
        client, member, {"recipe": "modal", "solver": "ansys", "material": MATERIAL}
    )
    assert original["status"] == "done"
    # 모의 실행기는 크기를 늘 적는다 — Mechanical 기본값으로 돈 작업처럼 요약에서 뺀다.
    row = db.get(Simulation, uuid.UUID(original["id"]))
    assert row is not None
    row.summary = {k: v for k, v in (row.summary or {}).items() if k != "element_size_mm"}
    db.commit()
    refused = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.7]},
        headers=member.headers,
    )
    assert refused.status_code == 400
    assert "비율을 곱할 기준이 없습니다" in refused.json()["error"]["message"]
    for body in ({"ratios": [0.7], "sizes_mm": [3]}, {}, {"ratios": [0]}):
        bad = client.post(
            f"/api/simulations/{original['id']}/convergence", json=body, headers=member.headers
        )
        assert bad.status_code in (400, 422), body


def test_쉘_파트가_있으면_중간면도_옮겨_점검한다(client: TestClient, member: Signed) -> None:
    """**형상 · 점 파일만 옮기면 쉘 작업은 점검 자체가 안 걸린다** — 만들 때 「중간면 형상을
    함께 올려야 합니다」(SIMULATIONS-0029)로 막혔다(2026-10-05, 조건_강체지그_쉘브래킷). 원래
    작업의 중간면(`input_mid.step`)을 수준마다 함께 싣는다."""
    files: dict[str, Any] = {
        "file": (
            "p0001.step",
            io.BytesIO((SHELL_POINTS / "p0001.step").read_bytes()),
            "model/step",
        ),
        "topology": (
            "p0001.json",
            io.BytesIO((SHELL_POINTS / "p0001.json").read_bytes()),
            "application/json",
        ),
        "midsurface": (
            "p0001_mid.step",
            io.BytesIO((SHELL_POINTS / "p0001_mid.step").read_bytes()),
            "model/step",
        ),
    }
    created = client.post(
        "/api/simulations",
        data={
            "spec": json.dumps({"recipe": "modal", "mesh": {"element_size_mm": 4}}),
            "workspace_slug": member.workspace,
        },
        files=files,
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    original = created.json()
    assert original["status"] == "done", original
    made = client.post(
        f"/api/simulations/{original['id']}/convergence",
        json={"ratios": [0.7]},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    level = next(one for one in made.json()["levels"] if not one["is_original"])
    job = client.get(
        f"/api/simulations/{level['simulation_id']}", headers=member.headers
    ).json()
    assert "input_mid_step" in {one["kind"] for one in job["artifacts"]}
