"""실측과 맞추기 — **올린 실측을 그 결과와 같은 자리에서 견주고, 차이를 변수로 설명하는가.**

비교 계산 자체는 `tests/unit/test_measured.py` 가 지킨다. 여기서는 올리기 · 권한 · 작업과
스터디에 붙이기 · 내리기, 그리고 모의 실행기의 결과로 끝까지 밟는 길을 본다.
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import get_settings
from app.modules.workspaces.models import Workspace
from tests.api.conftest import Signed, _login, _make_user

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
DOE = Path(__file__).resolve().parents[1] / "fixtures" / "doe"


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


def _create(
    client: TestClient, who: Signed, spec: dict[str, Any], topology: Path | None = None
) -> dict[str, Any]:
    files: dict[str, Any] = {"file": ("시편.step", io.BytesIO(STEP), "model/step")}
    if topology is not None:
        files["topology"] = (
            "topology.json",
            io.BytesIO(topology.read_bytes()),
            "application/json",
        )
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files=files,
        headers=who.headers,
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    assert body["status"] == "done", body
    return body


def _upload(
    client: TestClient, who: Signed, path: str, text: str, label: str = "시편 1"
) -> Any:
    return client.post(
        path,
        data={"label": label},
        files={"file": ("실측.csv", io.BytesIO(text.encode("utf-8")), "text/csv")},
        headers=who.headers,
    )


def test_공진을_올리면_모드와_짝짓고_영률로_차이를_설명한다(
    client: TestClient, member: Signed
) -> None:
    job = _create(client, member, {"recipe": "modal", "material": MATERIAL, "modes": 4})
    result = client.get(f"/api/simulations/{job['id']}/result", headers=member.headers).json()
    elastic = [one["frequency_hz"] for one in result["modes"] if not one["rigid_body"]]
    # 실측이 모든 모드에서 √(195/200) 배 — 영률 195 GPa 로 설명된다.
    ratio = math.sqrt(195 / 200)
    text = "측정점,종류,주파수\n" + "".join(f",공진,{hz * ratio:.4f}\n" for hz in elastic[:2])

    made = _upload(client, member, f"/api/simulations/{job['id']}/measurements", text)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["kinds"] == ["frequency"] and body["rows"] == 2
    found = body["comparison"]["frequency"]
    assert [one["elastic_number"] for one in found["matches"]] == [1, 2]
    assert found["suggested_modulus_gpa"] == pytest.approx(195, rel=1e-3)

    listed = client.get(f"/api/simulations/{job['id']}/measurements", headers=member.headers)
    assert [one["id"] for one in listed.json()] == [body["id"]]


def test_정적_변위와_변형률을_같은_자리에서_견준다(client: TestClient, member: Signed) -> None:
    """전단 이음 — **변위로 당긴 모델**이라 차이를 영률로 설명하지 않는다."""
    job = _create(
        client,
        member,
        {"recipe": "static", "material": MATERIAL},
        topology=DOE / "조건_전단이음" / "points" / "p0002.json",
    )
    result = client.get(f"/api/simulations/{job['id']}/result", headers=member.headers).json()
    upper = next(one for one in result["probes"] if one["name"] == "이음 입구 위판")
    text = (
        "측정점,종류,값,단위,성분\n"
        f"이음 입구 위판,변위,{upper['vector'][0] * 1000 * 1.1:.6f},um,x\n"
        f"이음 입구 위판,변형률,{upper['strain'][0] * 1e6:.3f},ue,x\n"
    )
    body = _upload(client, member, f"/api/simulations/{job['id']}/measurements", text).json()
    matches = body["comparison"]["static"]["matches"]
    displacement = next(one for one in matches if one["kind"] == "displacement")
    assert displacement["diff_pct"] == pytest.approx((1 / 1.1 - 1) * 100, rel=1e-3)
    strain = next(one for one in matches if one["kind"] == "strain")
    assert strain["diff_pct"] == pytest.approx(0.0, abs=0.01)
    assert body["comparison"]["static"]["suggested_modulus_gpa"] is None
    assert "변위로 당긴" in body["comparison"]["static"]["explanation"]


def test_FRF_를_측정점_곡선과_겹친다(client: TestClient, member: Signed) -> None:
    job = _create(
        client,
        member,
        {"recipe": "harmonic", "material": MATERIAL},
        topology=DOE / "조건_측면가진" / "points" / "p0001.json",
    )
    result = client.get(f"/api/simulations/{job['id']}/result", headers=member.headers).json()
    curve = [(one["frequency_hz"], one["probes"]["측정점"]) for one in result["points"]]
    text = "측정점,종류,주파수,값,단위\n" + "".join(
        f"측정점,FRF,{hz},{amplitude},mm\n" for hz, amplitude in curve
    )
    body = _upload(client, member, f"/api/simulations/{job['id']}/measurements", text).json()
    frf = body["comparison"]["frf"][0]
    assert frf["probe"] == "측정점"
    assert frf["peak_diff_pct"] == pytest.approx(0.0)
    assert frf["amplitude_ratio"] == pytest.approx(1.0)
    assert len(frf["measured"]) == len(frf["analysis"])


def test_틀린_표는_줄_번호와_함께_전부_돌려준다(client: TestClient, member: Signed) -> None:
    job = _create(client, member, {"recipe": "modal", "material": MATERIAL})
    got = _upload(
        client,
        member,
        f"/api/simulations/{job['id']}/measurements",
        "측정점,종류,주파수,값\nA,가속,100,1\nA,변위,,\n",
    )
    assert got.status_code == 400
    errors = got.json()["error"]["details"]["errors"]
    assert any(one.startswith("2줄") for one in errors)
    assert any(one.startswith("3줄") for one in errors)


def test_화면의_표는_JSON_으로_오고_가운데_빈_줄도_줄_번호를_지킨다(
    client: TestClient, member: Signed
) -> None:
    """화면의 실측 표(`MeasurementEntry`)는 로컬 파일 없이 **표 그대로 JSON** 으로 보낸다
    (회사 PC 의 DRM). 칸마다 열 이름이 붙고 빈 칸은 빈 글이다. 가운데 빈 줄도 보내야 서버의 줄
    번호가 화면의 줄 번호(+1, 머리줄)와 맞는다."""
    job = _create(client, member, {"recipe": "modal", "material": MATERIAL})
    blank = {"측정점": "", "종류": "", "주파수": "", "값": "", "단위": "", "성분": ""}
    rows = [
        {**blank, "종류": "공진", "주파수": "1250"},
        blank,
        {**blank, "측정점": "A", "종류": "가속", "주파수": "100", "값": "1"},
    ]
    body = json.dumps({"rows": rows}, ensure_ascii=False).encode("utf-8")
    bad = client.post(
        f"/api/simulations/{job['id']}/measurements",
        data={"label": "화면"},
        files={"file": ("화면 입력.json", io.BytesIO(body), "application/json")},
        headers=member.headers,
    )
    assert bad.status_code == 400
    # 화면의 3번 줄 = 서버의 4줄.
    assert [one[:2] for one in bad.json()["error"]["details"]["errors"]] == ["4줄"]

    good = json.dumps({"rows": rows[:2]}, ensure_ascii=False).encode("utf-8")
    made = client.post(
        f"/api/simulations/{job['id']}/measurements",
        data={"label": "화면"},
        files={"file": ("화면 입력.json", io.BytesIO(good), "application/json")},
        headers=member.headers,
    )
    assert made.status_code == 201, made.text
    assert made.json()["kinds"] == ["frequency"]


def test_스터디에_붙이면_설계점마다_견주고_가장_가까운_점을_고른다(
    client: TestClient, member: Signed
) -> None:
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(DOE / "조건_측면가진"),
            # 다른 시험이 같은 폴더를 가져갔을 수 있다 — 이 시험은 그 묶음에 실측을 붙인다.
            "spec": {"recipe": "harmonic", "material": MATERIAL},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    study_id = created.json()["study_id"]
    text = (
        "측정점,종류,주파수,값,단위\n"
        "측정점,FRF,500,0.01,mm\n측정점,FRF,520,0.02,mm\n측정점,FRF,540,0.01,mm\n"
    )
    made = _upload(client, member, f"/api/simulations/studies/{study_id}/measurements", text)
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["study_id"] == study_id
    assert len(body["points"]) >= 2
    assert body["best_point"] is not None
    assert "가장 가까운 설계점" in body["explanation"]

    listed = client.get(
        f"/api/simulations/studies/{study_id}/measurements", headers=member.headers
    ).json()
    assert body["id"] in {one["id"] for one in listed}

    # **스터디의 실측은 그 점의 작업 화면에도 나온다** — 그 결과와 견준 것으로.
    point = body["points"][0]["simulation_id"]
    on_job = client.get(
        f"/api/simulations/{point}/measurements", headers=member.headers
    ).json()
    assert body["id"] in {one["id"] for one in on_job}


def test_내린_실측은_목록에서_빠지고_남의_실측은_못_내린다(
    client: TestClient, db: Session, workspace: Workspace, member: Signed, manager: Signed
) -> None:
    """**올린 사람이거나 그 부서의 관리자**가 내린다 — 같은 부서의 다른 멤버는 못 내린다."""
    job = _create(client, member, {"recipe": "modal", "material": MATERIAL})
    body = _upload(
        client, member, f"/api/simulations/{job['id']}/measurements", "종류,주파수\n공진,300\n"
    ).json()
    path = f"/api/simulations/measurements/{body['id']}"

    other = _make_user(db, workspace, label="other", is_system_admin=False, role="member")
    other_headers = {"Authorization": f"Bearer {_login(client, other.email)}"}
    assert client.delete(path, headers=other_headers).status_code == 403

    assert client.delete(path, headers=manager.headers).status_code == 204
    listed = client.get(f"/api/simulations/{job['id']}/measurements", headers=member.headers)
    assert listed.json() == []
    # 이미 내린 것은 없는 것이다.
    assert client.delete(path, headers=member.headers).status_code == 404


def test_양식을_내려받는다(client: TestClient, member: Signed) -> None:
    got = client.get("/api/simulations/measurements/template.csv", headers=member.headers)
    assert got.status_code == 200
    text = got.content.decode("utf-8")
    assert text.startswith("﻿측정점,종류,주파수,값,단위,성분")
