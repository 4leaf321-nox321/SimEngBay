"""해석 작업 — 걸고, 돌고, 산출물을 받고, **못 볼 것은 못 본다.**

실행기는 fake 다(시험 `.env` 기본). `JOBS_INLINE` 을 켜서 요청 안에서 네 단계가 다 돈다 —
워커와
같은 `services.execute` 를 지나므로 상태 기계 · 산출물 등록 · 실패 기록이 여기서 검증된다.
"""

from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.stages import StageContext, StageFailure, StageResult
from app.modules.simulations import services
from app.modules.simulations.models import Simulation
from tests.api.conftest import Signed, maintenance_counts

STEP = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
MATERIAL = {
    "name": "SS400",
    "youngs_modulus_gpa": 200,
    "poisson_ratio": 0.3,
    "density_kg_m3": 7850,
}
MODAL: dict[str, Any] = {"recipe": "modal", "material": MATERIAL, "modes": 5}


@pytest.fixture(autouse=True)
def inline_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    """요청 안에서 돌린다. 워커 프로세스를 시험에서 띄우지 않는다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", True)


def _create(
    client: TestClient,
    who: Signed,
    *,
    spec: dict[str, Any] | None = None,
    content: bytes = STEP,
    name: str = "브래킷.step",
    workspace: str | None = None,
) -> Response:
    data: dict[str, str] = {"spec": json.dumps(spec if spec is not None else MODAL)}
    if workspace is not None:
        data["workspace_slug"] = workspace
    response: Response = client.post(
        "/api/simulations",
        data=data,
        files={"file": (name, io.BytesIO(content), "model/step")},
        headers=who.headers,
    )
    return response


def test_걸면_네_단계를_지나_done_이_되고_산출물이_남는다(
    client: TestClient, member: Signed
) -> None:
    """**부서 멤버면 건다.** 관리자만 걸게 하면 관리자가 대신 눌러 주는 일이 생기고, 그때
    걸었나」 가 거짓이 된다."""
    created = _create(client, member, workspace=member.workspace)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "done"
    assert body["name"] == "브래킷.step"
    assert [one["status"] for one in body["stages"]] == ["done", "done", "done", "done"]
    assert body["summary"]["modes"] == 5 + 6  # 자유-자유: 강체 6 + 탄성 5
    kinds = {one["kind"] for one in body["artifacts"]}
    assert kinds == {"input_step", "spec", "dat", "mechdb", "rst", "solve_out", "result_json"}

    # 산출물을 받으면 그 파일이다.
    result = next(one for one in body["artifacts"] if one["kind"] == "result_json")
    got = client.get(
        f"/api/simulations/{body['id']}/artifacts/{result['id']}/content",
        headers=member.headers,
    )
    assert got.status_code == 200, got.text
    assert got.json()["boundary"] == "free-free"

    # 폴링 경로는 상세와 같은 것을 준다.
    polled = client.get(f"/api/simulations/{body['id']}/status", headers=member.headers)
    assert polled.status_code == 200
    assert polled.json()["status"] == "done"


def test_스펙이_틀리면_걸기_전에_어느_칸인지_말한다(
    client: TestClient, member: Signed
) -> None:
    bad = {"recipe": "modal", "material": {**MATERIAL, "poisson_ratio": 0.7}}
    response = _create(client, member, spec=bad, workspace=member.workspace)
    assert response.status_code == 400, response.text
    assert "poisson_ratio" in response.json()["error"]["message"]

    unknown = {"recipe": "modal", "material": MATERIAL, "solver": "sparse"}
    response = _create(client, member, spec=unknown, workspace=member.workspace)
    assert response.status_code == 400

    response = client.post(
        "/api/simulations",
        data={"spec": "{not json", "workspace_slug": member.workspace},
        files={"file": ("a.step", io.BytesIO(STEP), "model/step")},
        headers=member.headers,
    )
    assert response.status_code == 400


def test_정적_해석도_걸_수_있다(client: TestClient, member: Signed) -> None:
    """**2026-10-02 부터 `static` 도 돈다.** 하중을 걸고 변형 · 응력을 본다.

    구속은 CAD 조건에서 오므로 스펙에는 없어도 된다 — 지문 없이 구속을 적으면 그때는 거절한다
    (아래 시험이 그 자리다).
    """
    static = {"recipe": "static", "material": MATERIAL}
    response = _create(client, member, spec=static, workspace=member.workspace)
    assert response.status_code == 201, response.text
    assert response.json()["recipe"] == "static"


def test_모르는_레시피는_거절한다(client: TestClient, member: Signed) -> None:
    """레시피 이름이 틀리면 **걸기 전에** 막는다 — 워커가 집어 들고 나서 죽으면 사람은 「왜
    실패했나」 를 목록에서 찾아야 한다."""
    response = _create(
        client,
        member,
        spec={"recipe": "thermal", "material": MATERIAL},
        workspace=member.workspace,
    )
    assert response.status_code == 400


def test_빈_형상은_걸지_않는다(client: TestClient, member: Signed) -> None:
    response = _create(client, member, content=b"", workspace=member.workspace)
    assert response.status_code == 400
    assert "빈 파일" in response.json()["error"]["message"]


def test_전역_작업은_시스템_관리자만(
    client: TestClient, member: Signed, admin: Signed
) -> None:
    denied = _create(client, member)
    assert denied.status_code == 403
    allowed = _create(client, admin)
    assert allowed.status_code == 201, allowed.text
    assert allowed.json()["owner_workspace_id"] is None


def test_남의_닫힌_부서_작업은_보이지_않는다(
    client: TestClient, db: Session, member: Signed, admin: Signed
) -> None:
    """보이는 것은 `open_owner_clause` — 전역 + 열린 부서 + 내 부서. 닫힌 남의 부서 것은 없는
    것과 같게 답한다(403 으로 가르면 id 가 존재한다는 사실이 샌다)."""
    from app.modules.workspaces.models import Workspace

    other = Workspace(slug="closed-lab", name="닫힌 연구소", restricted=True)
    db.add(other)
    db.commit()
    created = _create(client, admin, workspace="closed-lab")
    assert created.status_code == 201, created.text
    hidden_id = created.json()["id"]

    got = client.get(f"/api/simulations/{hidden_id}", headers=member.headers)
    assert got.status_code == 404
    listed = client.get("/api/simulations", headers=member.headers)
    assert hidden_id not in {one["id"] for one in listed.json()["items"]}


class _FailingExecutor:
    """솔버에서 라이선스를 못 받는 실행기.

    **규약을 진짜 실행기와 같게 둔다**(`should_cancel`) — 다르면 부르는 쪽이 바뀔 때 이 대역만
    조용히 터지고, 그 실패는 「라이선스」 가 아니라 「internal」 로 나타난다(실측).
    """

    name = "failing"

    def run(
        self, ctx: StageContext, should_cancel: Callable[[], bool] | None = None
    ) -> StageResult:
        if ctx.stage == "solving":
            raise StageFailure("license", "솔버 라이선스를 받지 못했습니다.")
        return StageResult(detail="ok")


def test_실패는_어느_단계가_왜인지_남기고_재시도할_수_있다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = services.default_executor
    monkeypatch.setattr(services, "default_executor", lambda: _FailingExecutor())
    created = _create(client, member, workspace=member.workspace)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "license"
    assert [one["status"] for one in body["stages"]] == ["done", "done", "failed", "skipped"]
    assert body["stages"][2]["error_message"] == "솔버 라이선스를 받지 못했습니다."

    # 홈의 「남은 일」 에 실패가 뜬다.
    assert maintenance_counts(client, member).get("simulations_failed", 0) >= 1

    # 실행기를 고치고 재시도하면 처음부터 다시 돌아 done 이 된다.
    monkeypatch.setattr(services, "default_executor", original)
    retried = client.post(f"/api/simulations/{body['id']}/retry", headers=member.headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "done"
    assert retried.json()["error_code"] is None
    assert retried.json()["attempts"] == 2

    # done 인 것은 재시도할 수 없다.
    again = client.post(f"/api/simulations/{body['id']}/retry", headers=member.headers)
    assert again.status_code == 409


def test_개인_토큰은_쓰기_범위가_있어야_건다(client: TestClient, member: Signed) -> None:
    """오케스트레이터가 붙는 길. 읽기 토큰으로는 못 걸고, `simulations:write` 면 건다."""
    read_only = client.post("/api/auth/tokens", json={"name": "읽기"}, headers=member.headers)
    token = read_only.json()["token"]
    denied = _create(
        client,
        Signed(email=member.email, token=token, workspace=member.workspace),
        workspace=member.workspace,
    )
    assert denied.status_code == 403

    writer = client.post(
        "/api/auth/tokens",
        json={"name": "오케스트레이터", "scopes": ["read", "simulations:write"]},
        headers=member.headers,
    )
    assert writer.status_code == 201, writer.text
    token = writer.json()["token"]
    allowed = _create(
        client,
        Signed(email=member.email, token=token, workspace=member.workspace),
        workspace=member.workspace,
    )
    assert allowed.status_code == 201, allowed.text


def test_목록은_쪽으로_나뉘고_상태로_거른다(client: TestClient, member: Signed) -> None:
    for _ in range(3):
        assert _create(client, member, workspace=member.workspace).status_code == 201
    page = client.get(
        f"/api/simulations?limit=2&status=done&workspace_slug={member.workspace}",
        headers=member.headers,
    )
    assert page.status_code == 200, page.text
    body = page.json()
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["total"] >= 3
    assert all(one["status"] == "done" for one in body["items"])
    # 목록 한 줄은 스펙 · 단계를 싣지 않는다.
    assert "stages" not in body["items"][0]


def test_워커_경로도_같은_함수를_지난다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """인라인을 끄면 queued 로 남고, 워커의 claim → execute 가 그것을 끝낸다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    assert created.status_code == 201
    assert created.json()["status"] == "queued"

    claimed = services.claim_next(db, "test-worker")
    assert claimed is not None
    assert claimed.status == "fetching"
    done = services.execute(db, claimed, worker_id="test-worker")
    assert done.status == "done"
    assert done.worker_id == "test-worker"
    assert done.attempts == 1


def test_워커는_제_솔버의_작업만_집는다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**Ansys 는 워커 하나 · CalculiX 는 여럿** — 그래서 집는 작업을 솔버로 가른다.

    Ansys 는 노드락 라이선스가 하나라 워커를 늘리면 나머지가 라이선스 오류로 실패한다.
    CalculiX 는 라이선스가 없어 코어 수만큼 띄울 수 있다. 구분이 없으면 CalculiX 를 늘리려다
    **Ansys 작업을 깨뜨린다** — 그 사고는 「해석이 실패했다」 로만 보인다.
    """
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    ansys_job = _create(client, member, workspace=member.workspace)
    assert ansys_job.status_code == 201
    open_job = _create(
        client, member, spec={**MODAL, "solver": "calculix"}, workspace=member.workspace
    )
    assert open_job.status_code == 201, open_job.text

    # CalculiX 워커는 **먼저 들어온 Ansys 작업을 건너뛴다**(순서보다 솔버가 먼저다).
    picked = services.claim_next(db, "open-worker", solvers=("calculix",))
    assert picked is not None
    assert str(picked.id) == open_job.json()["id"]

    # Ansys 워커는 자기 것을 집는다.
    other = services.claim_next(db, "ansys-worker", solvers=("ansys",))
    assert other is not None
    assert str(other.id) == ansys_job.json()["id"]

    # 더 집을 것이 없다.
    assert services.claim_next(db, "open-worker", solvers=("calculix",)) is None


def test_솔버_칸이_없는_옛_작업은_ansys_로_본다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """스펙의 기본값과 같게 본다.

    안 그러면 옛 작업이 **아무 워커도 안 집어** 영원히 대기한다.
    """
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, spec=MODAL, workspace=member.workspace)
    assert created.status_code == 201
    assert "solver" not in MODAL, "이 시험은 솔버 칸이 없는 스펙이어야 뜻이 있다"

    assert services.claim_next(db, "open-worker", solvers=("calculix",)) is None
    picked = services.claim_next(db, "ansys-worker", solvers=("ansys",))
    assert picked is not None
    assert str(picked.id) == created.json()["id"]


def test_결과_요약은_파일_그대로_온다(client: TestClient, member: Signed) -> None:
    """**DB 에 옮겨 담지 않는다** — 해석이 낸 파일이 정본이고, 표로 복사하면 두 벌이 갈린다."""
    created = _create(client, member, workspace=member.workspace)
    assert created.status_code == 201, created.text

    got = client.get(f"/api/simulations/{created.json()['id']}/result", headers=member.headers)
    assert got.status_code == 200, got.text
    result = got.json()
    assert result["recipe"] == "modal"
    assert result["boundary"] == "free-free"
    assert result["units"]["frequency"] == "Hz"
    assert result["normalization"] == "mass"
    assert result["rigid_body_modes"] == 6
    # 화면이 탄성 모드만 골라 그릴 수 있어야 한다.
    elastic = [one for one in result["modes"] if not one["rigid_body"]]
    assert [one["elastic_number"] for one in elastic] == [1, 2, 3, 4, 5]


def test_아직_안_끝난_작업은_결과가_없다고_말한다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """404 에 **왜** 없는지를 싣는다 — 「없다」 만 오면 사람은 서버가 고장난 줄 안다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    got = client.get(f"/api/simulations/{created.json()['id']}/result", headers=member.headers)
    assert got.status_code == 404
    assert got.json()["error"]["details"]["status"] == "queued"


def _topology_bytes() -> bytes:
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "topology"
        / "plate_holes.topology.json"
    )
    return path.read_bytes()


FIXED = {**MODAL, "constraints": [{"region": "fixed_base", "kind": "fixed"}]}


def test_구속이_있는데_영역_지문이_없으면_걸기_전에_막는다(
    client: TestClient, member: Signed
) -> None:
    """그대로 보내면 1분 뒤 모델링 단계에서 같은 말을 듣는다.

    그 1분 동안 Mechanical 라이선스도 함께 물고 있다.
    """
    response = _create(client, member, spec=FIXED, workspace=member.workspace)
    assert response.status_code == 400, response.text
    assert "topology.json" in response.json()["error"]["message"]


def test_영역_지문을_함께_올리면_산출물로_남는다(client: TestClient, member: Signed) -> None:
    created = client.post(
        "/api/simulations",
        data={"spec": json.dumps(FIXED), "workspace_slug": member.workspace},
        files={
            "file": ("bracket.step", io.BytesIO(STEP), "model/step"),
            "topology": ("topology.json", io.BytesIO(_topology_bytes()), "application/json"),
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    kinds = {one["kind"] for one in created.json()["artifacts"]}
    assert "topology" in kinds


def test_영역_지문이_CAD_가_낸_것이_아니면_거절한다(
    client: TestClient, member: Signed
) -> None:
    response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(FIXED), "workspace_slug": member.workspace},
        files={
            "file": ("bracket.step", io.BytesIO(STEP), "model/step"),
            "topology": ("topology.json", io.BytesIO(b'{"hello": 1}'), "application/json"),
        },
        headers=member.headers,
    )
    assert response.status_code == 400
    assert "regions" in response.json()["error"]["message"]


DOE_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"
)


def test_DOE_폴더를_걸기_전에_보여_준다(client: TestClient, member: Signed) -> None:
    """**먼저 보여 주고 나서 건다** — 200개를 잘못 걸면 되돌리기 어렵다."""
    got = client.get(f"/api/simulations/doe/preview?path={DOE_FOLDER}", headers=member.headers)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["name"] == "브래킷_두께훑기"
    assert body["factors"] == ["두께"]
    assert body["usable"] == 3
    assert body["skipped"] == 1
    # 건너뛰는 줄은 **이유**를 달고 온다.
    skipped = next(one for one in body["points"] if not one["usable"])
    assert "벽이 판을 넘습니다" in skipped["skip_reason"]


SHEAR_FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_전단이음"


def test_미리보기가_CAD_가_적은_해석_종류와_요소_크기를_알려_준다(
    client: TestClient, member: Signed
) -> None:
    """**해석 종류는 점 파일의 `conditions.analysis.type` 이다** — 화면이 모달로 못 박아
    두면 전단 이음(정적)이 하중을 건너뛴 채 모달로 돈다. 요소 크기는 CalculiX 가 꼭 받아야 하는
    값이라 「전체」 힌트를 mm 로 옮겨 함께 낸다."""
    got = client.get(
        f"/api/simulations/doe/preview?path={SHEAR_FOLDER}", headers=member.headers
    )
    assert got.status_code == 200, got.text
    assert got.json()["suggested_recipe"] == "static"
    assert got.json()["suggested_element_size_mm"] == 2.5

    # 아무것도 안 적은 옛 폴더는 **비워 둔다** — 「CAD 가 모달이라 했다」 로 채우면 거짓이다.
    bare = client.get(
        f"/api/simulations/doe/preview?path={DOE_FOLDER}", headers=member.headers
    )
    assert bare.json()["suggested_recipe"] is None
    assert bare.json()["suggested_element_size_mm"] is None


MATERIAL_SWEEP_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_재료훑기"
)
SIDE_SHAKE_FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_측면가진"


def test_DOE_를_CalculiX_로_가져오면_점마다_그_솔버가_적힌다(
    client: TestClient, member: Signed
) -> None:
    """솔버는 **스펙에 실려** 점마다 저장된다 — CalculiX 만 집는 워커가 그것으로 고른다."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(MATERIAL_SWEEP_FOLDER),
            "spec": {
                "recipe": "static",
                "solver": "calculix",
                "material": MODAL["material"],
            },
            "workspace_slug": member.workspace,
            "numbers": [1],
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    first = created.json()["created"][0]
    one = client.get(f"/api/simulations/{first}", headers=member.headers).json()
    assert one["spec"]["solver"] == "calculix"
    assert one["recipe"] == "static"
    # 목록 줄에도 솔버가 실린다 — 스펙을 다 싣지 않고도 가를 수 있게.
    listed = client.get("/api/simulations?limit=200", headers=member.headers).json()["items"]
    assert next(row for row in listed if row["id"] == first)["solver"] == "calculix"


def test_CAD_점_파일을_걸기_전에_읽어_준다(client: TestClient, member: Signed) -> None:
    """**새 작업 창이 점 파일을 따로 해석하지 않는다** — 작업을 거는 길과 같은 코드가 읽어,
    무엇이 들었고(영역 · 물성 · 해석 설정) 그 해석 종류에서 조건이 어떻게 다뤄지나를 준다."""
    point = SHEAR_FOLDER / "points" / "p0002.json"
    got = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("p0002.json", point.read_bytes(), "application/json")},
        headers=member.headers,
    )
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["suggested_recipe"] == "static" and body["recipe"] == "static"
    assert body["suggested_element_size_mm"] == 2.5
    # 「전체」 요소 차수도 제안한다 — 창이 미리 채운다.
    assert body["suggested_order"] == "quadratic"
    # **파트가 여럿이면 파트마다 붙을 재료를 보여 준다** — 모델링과 같은 규칙으로 짝짓는다.
    assert [(one["name"], one["material"]) for one in body["bodies"]] == [
        ("아래판", "SECC-EXAD87-DP_선언물성_0.8"),
        ("위판", "AL5052H32DEMO_-_-"),
    ]
    steel = body["materials"][0]
    assert steel["bodies"] == ["아래판"] and 150 < steel["youngs_modulus_gpa"] < 250
    assert body["material_error"] == ""
    kinds = {one["name"]: one["kind"] for one in body["regions"]}
    assert kinds["이음 입구 위판"] == "point"
    lines = body["conditions"]["lines"]
    assert any(one["kind"] == "load" and one["status"] == "applied" for one in lines)

    # 모달로 물으면 하중을 **넘긴다**고 말한다 — 조용히 버리지 않는다.
    modal = client.post(
        "/api/simulations/conditions/preview",
        data={"recipe": "modal"},
        files={"file": ("p0002.json", point.read_bytes(), "application/json")},
        headers=member.headers,
    ).json()
    assert any(one["status"] == "skipped" for one in modal["conditions"]["lines"])

    bad = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("x.json", b'{"nope": 1}', "application/json")},
        headers=member.headers,
    )
    assert bad.status_code == 400
    assert "regions" in bad.json()["error"]["message"]


TWO_BODY_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_두바디_두재료"
)


def _create_with_point(
    client: TestClient, who: Signed, spec: dict[str, Any], point: bytes | None
) -> Response:
    files: dict[str, Any] = {"file": ("조립.step", io.BytesIO(STEP), "model/step")}
    if point is not None:
        files["topology"] = ("p0001.json", io.BytesIO(point), "application/json")
    response: Response = client.post(
        "/api/simulations",
        data={"spec": json.dumps(spec), "workspace_slug": who.workspace},
        files=files,
        headers=who.headers,
    )
    return response


def test_CAD_가_물성을_보내면_스펙에_물성이_없어도_된다(
    client: TestClient, member: Signed
) -> None:
    """**물성은 CompCore 가 파트마다 정한다.** 화면은 물성을 받지 않는다 — 한 벌을 모든 파트에
    붙이는 것은 조립품에서 뜻이 없다. 점 파일의 재료가 파트마다 붙는다."""
    point = (TWO_BODY_FOLDER / "points" / "p0001.json").read_bytes()
    created = _create_with_point(client, member, {"recipe": "modal", "modes": 5}, point)
    assert created.status_code == 201, created.text
    assert created.json()["spec"]["material"] is None


def test_물성이_아무_데도_없으면_만들_때_거절한다(client: TestClient, member: Signed) -> None:
    """워커가 집어 들고 모델링에서야 「물성이 없다」 고 하면, 사람은 1분 뒤 목록에서 그 말을
    찾는다. 만들 때 막는다."""
    bare = _create_with_point(client, member, {"recipe": "modal"}, None)
    assert bare.status_code == 400
    assert "물성" in bare.json()["error"]["message"]

    # 점 파일이 있어도 물성을 안 보냈으면 마찬가지다(옛 영역 지문).
    old = (TOPOLOGY_FIXTURES / "plate_holes.topology.json").read_bytes()
    no_material = _create_with_point(client, member, {"recipe": "modal"}, old)
    assert no_material.status_code == 400
    assert "CompCore 에서 재료를 지정" in no_material.json()["error"]["message"]

    # **재료가 빠진 파트**가 있으면 — 모델링이 멈출 자리다. 사람이 준 한 벌로 메우지 않는다.
    payload = json.loads((TWO_BODY_FOLDER / "points" / "p0001.json").read_text("utf-8"))
    payload["conditions"]["materials"] = payload["conditions"]["materials"][:1]
    half = _create_with_point(
        client,
        member,
        {"recipe": "modal", "material": MATERIAL},
        json.dumps(payload, ensure_ascii=False).encode(),
    )
    assert half.status_code == 400
    assert "블록" in half.json()["error"]["message"]

    # 「내 값으로」 를 골랐는데 값이 없으면 스펙에서 거절한다.
    mine = _create_with_point(
        client, member, {"recipe": "modal", "material_from": "spec"}, None
    )
    assert mine.status_code == 400


def test_파트별_설정을_미리보기에_싣고_뺀_파트는_물성을_안_묻는다(
    client: TestClient, member: Signed
) -> None:
    """CompCore `body_settings`(2026-10-04) — **뺀 파트는 메시에도 안 나오므로 물성이 필요
    없다.** 강체 · 메시는 파트 표의 한 줄로, 쉘은 막은 조건으로 보인다."""
    payload = json.loads((TWO_BODY_FOLDER / "points" / "p0001.json").read_text("utf-8"))
    payload["conditions"]["materials"] = payload["conditions"]["materials"][
        :1
    ]  # 블록 재료 없음
    payload["conditions"]["body_settings"] = [
        {"name": "받침판", "behavior": "rigid", "mesh": {"element_size": 4}},
        {"name": "블록", "suppressed": True},
    ]
    raw = json.dumps(payload, ensure_ascii=False).encode()
    body = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("p0001.json", raw, "application/json")},
        headers=member.headers,
    ).json()
    parts = {one["name"]: one for one in body["bodies"]}
    assert parts["받침판"]["setting"] == "강체 · 요소 4"
    assert parts["블록"]["suppressed"] is True and parts["블록"]["material"] is None
    assert ("body", "파트 받침판") in {
        (one["kind"], one["label"]) for one in body["conditions"]["lines"]
    }

    created = _create_with_point(client, member, {"recipe": "modal", "modes": 5}, raw)
    assert created.status_code == 201, created.text

    payload["conditions"]["body_settings"] = [{"name": "블록", "representation": "shell"}]
    shell = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("p0001.json", json.dumps(payload).encode(), "application/json")},
        headers=member.headers,
    ).json()
    refused = [one for one in shell["conditions"]["lines"] if one["status"] == "refused"]
    assert refused and "쉘" in refused[0]["label"]


TOPOLOGY_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "topology"


def test_조건_없는_옛_지문도_영역과_면_수를_읽는다(client: TestClient, member: Signed) -> None:
    """CompCore 가 제 코드로 낸 옛 영역 지문(조건 없음) — 영역 이름 · 면 수 · 바디만 있다.
    화면이 고를 영역이 이것이다(전에는 브라우저가 따로 읽었다 — 이제 거는 길과 같은 코드가
    읽는다)."""
    raw = (TOPOLOGY_FIXTURES / "plate_holes.topology.json").read_bytes()
    body = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("plate_holes.topology.json", raw, "application/json")},
        headers=member.headers,
    ).json()
    assert [(one["name"], one["count"], one["kind"]) for one in body["regions"]] == [
        ("fixed_base", 1, "face"),
        ("bolt_holes", 4, "face"),
    ]
    # 옛 지문은 물성을 안 보낸다 — 파트 이름만 있고 붙을 재료가 없다(사람이 지정한다).
    assert [(one["name"], one["material"]) for one in body["bodies"]] == [("전체", None)]
    assert body["materials"] == []
    assert body["unresolved"] == []
    assert body["conditions"]["lines"] == []
    assert body["suggested_recipe"] is None


def test_DOE_미리보기가_첫_점의_조건을_해석_종류별로_보여_준다(
    client: TestClient, member: Signed
) -> None:
    got = client.get(
        f"/api/simulations/doe/preview?path={SHEAR_FOLDER}&recipe=modal",
        headers=member.headers,
    ).json()
    lines = got["conditions"]["lines"]
    assert any(one["kind"] == "constraint" for one in lines)
    assert any(one["status"] == "skipped" for one in lines), "모달이면 하중을 넘긴다"
    bare = client.get(
        f"/api/simulations/doe/preview?path={DOE_FOLDER}", headers=member.headers
    )
    assert bare.json()["conditions"] is None


def test_공용_폴더_밖은_아예_못_본다(client: TestClient, member: Signed) -> None:
    """**아무 경로나 받으면 그 칸이 서버의 모든 폴더를 여는 문이 된다** — 데이터 소스 폴더에
    이미 적혀 있는 규칙이다. 설정이 비어 있는 것과 밖을 가리킨 것은 다른 말로 답한다."""
    got = client.get("/api/simulations/doe/preview?path=/tmp", headers=member.headers)
    assert got.status_code == 400
    assert "공용 폴더 밖" in got.json()["error"]["message"]
    # 어디가 뿌리인지 함께 준다 — 사람이 다른 폴더를 고를 수 있어야 한다.
    assert got.json()["error"]["details"]["roots"]


def test_뿌리_안이라도_DOE_가_아니면_무엇이_없는지_말한다(
    client: TestClient, member: Signed
) -> None:
    got = client.get(
        f"/api/simulations/doe/preview?path={DOE_FOLDER.parent}", headers=member.headers
    )
    assert got.status_code == 400
    assert "manifest.csv" in got.json()["error"]["message"]


def test_공용_폴더를_탐색기처럼_훑는다(client: TestClient, member: Signed) -> None:
    """경로를 외워서 치게 하지 않는다 — 뿌리부터 폴더를 눌러 들어간다."""
    got = client.get("/api/simulations/doe/browse", headers=member.headers)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["roots"]
    names = {one["name"]: one for one in body["entries"]}
    assert "브래킷_두께훑기-3f9a2177" in names
    # **가져올 수 있는 폴더인지 표시한다**(manifest.csv 가 있나) — 눌러 보고 알게 하지 않는다.
    assert names["브래킷_두께훑기-3f9a2177"]["is_study"] is True


def test_뿌리_위로는_못_올라간다(client: TestClient, member: Signed) -> None:
    got = client.get("/api/simulations/doe/browse", headers=member.headers)
    assert got.json()["parent"] is None

    inside = client.get(
        f"/api/simulations/doe/browse?path={DOE_FOLDER}", headers=member.headers
    )
    assert inside.status_code == 200
    # 한 칸 위(뿌리)로는 올라갈 수 있다.
    assert inside.json()["parent"] == str(DOE_FOLDER.parent)
    assert inside.json()["is_study"] is True


def test_점_찍고_올라가는_길도_막는다(client: TestClient, member: Signed) -> None:
    """`..` 이나 심볼릭 링크로 밖을 가리키는 길 — **푼 다음에** 견줘야 막힌다."""
    got = client.get(
        f"/api/simulations/doe/browse?path={DOE_FOLDER}/../../../..", headers=member.headers
    )
    assert got.status_code == 400
    assert "공용 폴더 밖" in got.json()["error"]["message"]


def test_DOE_를_가져오면_설계점마다_작업이_생긴다(client: TestClient, member: Signed) -> None:
    """**CAD 로 되돌려 보내지 않으므로** 「이 결과가 두께 몇짜리인가」 를 이 플랫폼이 들고
    있어야 한다 — 작업마다 스터디 · 점 번호 · 바꾼 변수가 붙는다."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(DOE_FOLDER),
            "spec": {**MODAL, "constraints": [{"region": "bolt_holes", "kind": "fixed"}]},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert len(body["created"]) == 3
    assert len(body["skipped"]) == 1

    one = client.get(f"/api/simulations/{body['created'][0]}", headers=member.headers).json()
    assert one["source_kind"] == "doe_point"
    assert one["source_meta"]["study_name"] == "브래킷_두께훑기"
    assert one["source_meta"]["params"] == {"두께": 6.0}
    # **같은 STEP 을 가리키는 점들은 같은 형상이다** — 그 열쇠가 경로 그 자체다.
    assert one["source_meta"]["shape_key"] == "points/p0001.step"
    # 점마다의 영역 지문이 함께 실린다 — 구속을 걸 수 있다.
    assert "topology" in {artifact["kind"] for artifact in one["artifacts"]}
    assert "두께 6" in one["name"]


def test_DOE_는_물성이_빠지는_점을_걸지_않고_까닭을_단다(
    client: TestClient, member: Signed, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """화면에서 물성을 안 받았으면 **CAD 가 보낸 물성으로만** 돈다 — 물성을 안 보낸 폴더의
    점은 걸지 않고 까닭을 단다(200점이 모델링에서 하나씩 실패하게 두지 않는다)."""
    # 다른 시험이 이미 가져간 폴더다 — 스터디 id 를 바꾼 사본으로 「이미 가져온 점」 을 피한다.
    folder = tmp_path / "브래킷_물성없음"
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = "0" * 32
    (folder / "study.json").write_text(json.dumps(study), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "doe_roots", str(tmp_path))
    bare = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(folder),
            "spec": {"recipe": "modal"},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert bare.status_code == 201, bare.text
    assert bare.json()["created"] == []
    reasons = [one["skip_reason"] for one in bare.json()["skipped"]]
    assert sum("물성이 없습니다" in one for one in reasons) == 3, reasons
    monkeypatch.undo()

    with_cad = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(TWO_BODY_FOLDER),
            "spec": {"recipe": "modal"},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert with_cad.status_code == 201, with_cad.text
    assert len(with_cad.json()["created"]) == 2


SHELL_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "조건_강체지그_쉘브래킷"
)


def test_쉘_파트가_있으면_중간면_형상을_함께_싣는다(
    client: TestClient, member: Signed
) -> None:
    """CompCore v0.8.1 — 쉘 파트가 있으면 설계점마다 `pNNNN_mid.step` 이 나간다. DOE 를
    가져오면 그것이 작업에 함께 실리고(`input_mid_step`), 하나씩 올릴 때 빠뜨리면 만들 때
    막는다(모델링이 1분 뒤 같은 말을 하게 두지 않는다)."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(SHELL_FOLDER),
            "spec": {"recipe": "static", "solver": "calculix"},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    assert len(created.json()["created"]) == 2
    one = client.get(
        f"/api/simulations/{created.json()['created'][0]}", headers=member.headers
    ).json()
    assert "input_mid_step" in {artifact["kind"] for artifact in one["artifacts"]}

    point = (SHELL_FOLDER / "points" / "p0001.json").read_bytes()
    preview = client.post(
        "/api/simulations/conditions/preview",
        files={"file": ("p0001.json", point, "application/json")},
        headers=member.headers,
    ).json()
    parts = {row["name"]: row for row in preview["bodies"]}
    assert parts["브래킷"]["shell"] and parts["브래킷"]["setting"].startswith(
        "변형체 · 쉘 2 mm"
    )
    assert parts["명판"]["suppressed"] and not parts["지그블록"]["shell"]

    bare = _create_with_point(client, member, {"recipe": "static"}, point)
    assert bare.status_code == 400
    assert "중간면" in bare.json()["error"]["message"]


SINGLE_FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "설계하나_측면가진"


def test_설계_하나를_폴더에서_골라_작업으로_만든다(client: TestClient, member: Signed) -> None:
    """CompCore v0.9.0 「해석용으로 내보내기」 — 인자 0개 DOE 폴더(`factors: []`)가 설계
    하나다.

    폴더는 CompCore 공식 픽스처다(커밋 2b7d78d — 측면가진 · 기둥 높이 100). 새 작업 창이
    폴더에서 설계점 하나를 고르는 길이다: 미리보기는 그 점 파일을 올렸을 때와 같고, 만든 작업은
    **스터디가 아니다**(출처 `design`) — 스터디 목록 · 비교에 섞이지 않는다.
    """
    folder = client.get(
        f"/api/simulations/doe/preview?path={SINGLE_FOLDER}", headers=member.headers
    ).json()
    assert folder["single"] is True and folder["factors"] == []
    assert [one["number"] for one in folder["points"]] == [1]

    point = client.get(
        f"/api/simulations/doe/point?path={SINGLE_FOLDER}&number=1", headers=member.headers
    )
    assert point.status_code == 200, point.text
    parts = {row["name"]: row["material"] for row in point.json()["bodies"]}
    assert set(parts) == {"받침판", "기둥"} and all(parts.values())
    assert point.json()["suggested_recipe"] == "harmonic"
    missing = client.get(
        f"/api/simulations/doe/point?path={SINGLE_FOLDER}&number=7", headers=member.headers
    )
    assert missing.status_code == 400

    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(SINGLE_FOLDER),
            "spec": {"recipe": "modal", "modes": 4},
            "workspace_slug": member.workspace,
            "numbers": [1],
            "name": "기둥 받침 확인",
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    (made,) = created.json()["created"]
    one = client.get(f"/api/simulations/{made}", headers=member.headers).json()
    assert one["name"] == "기둥 받침 확인"
    assert one["source_kind"] == "design"
    studies = client.get("/api/simulations/studies", headers=member.headers).json()
    assert all(row["study_id"] != folder["study_id"] for row in studies)


SHARED_FOLDER = Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "재료훑기-7c1d3a44"


def test_형상을_나눠_쓰는_DOE_도_가져온다(client: TestClient, member: Signed) -> None:
    """**조건만 훑는 DOE 는 STEP 한 벌을 여러 점이 나눠 쓴다**(CompCore 2026-09-24 계약).

    그때 파일은 `points/pNNNN.step` 이 아니라 `shapes/<지문>.step` 에 있다 — 이름을 짐작하고
    찾으면 폴더 전체가 「형상 없음」 으로 건너뛰어지고, 사람은 CompCore 를 의심한다.
    """
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(SHARED_FOLDER),
            "spec": MODAL,
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["skipped"] == []
    assert len(body["created"]) == 2

    jobs = [
        client.get(f"/api/simulations/{one}", headers=member.headers).json()
        for one in body["created"]
    ]
    # 두 점은 **같은 형상**이다 — 그래서 모델링 · 메시를 다시 할 이유가 없다(열쇠가 같다).
    assert {one["source_meta"]["shape_key"] for one in jobs} == {"shapes/8f3a1c92.step"}
    assert all(one["source_meta"]["has_conditions"] for one in jobs)
    # **어느 계로 온 값인가** — 모델링이 이 선언대로 세션을 세운다(2026-09-24 결정 1+3).
    assert {one["source_meta"]["unit_system"] for one in jobs} == {"mm_n_tonne"}
    # 숫자가 아닌 인자도 이름에 남는다 — 표에서 둘을 구별할 수 있어야 한다.
    assert {one["source_meta"]["params"]["재료"] for one in jobs} == {"SS400", "AL6061"}
    assert any("SS400" in one["name"] for one in jobs)
    # 나눠 쓰는 형상도 **작업마다 한 벌씩** 들어온다 — 폴더가 사라져도 돌 수 있어야 한다.
    for one in jobs:
        steps = [art for art in one["artifacts"] if art["kind"] == "input_step"]
        assert len(steps) == 1
        assert steps[0]["size_bytes"] > 0


def test_고른_점만_가져올_수_있다(client: TestClient, member: Signed) -> None:
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(DOE_FOLDER),
            "spec": MODAL,
            "workspace_slug": member.workspace,
            "numbers": [2],
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    # 앞 시험이 이미 같은 폴더를 가져왔다 — **두 번째는 걸지 않고 그 사실을 말한다.**
    body = created.json()
    assert len(body["created"]) + len(body["skipped"]) == 1


def test_같은_DOE_를_두_번_가져와도_두_벌이_안_생긴다(
    client: TestClient, member: Signed
) -> None:
    """폴더 경로를 다시 붙여넣는 일은 흔하다.

    그때 조용히 두 벌이 돌면 **Mechanical 라이선스를 두 번 태운다.**
    """
    again = client.post(
        "/api/simulations/doe/import",
        json={"path": str(DOE_FOLDER), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    assert again.status_code == 201, again.text
    body = again.json()
    assert body["created"] == []
    assert any("이미 가져온 점" in one["skip_reason"] for one in body["skipped"])


def test_정적_DOE_비교에_반력과_측정점이_실린다(client: TestClient, member: Signed) -> None:
    """**정적 DOE 는 모드가 아니라 힘과 변위를 견준다** — 전단 이음이면 「μ 를 바꾸면 반력과
    미끄럼이 어떻게 변하나」 가 그 물음이다. 값은 늘 mm · N 이다(솔버마다 단위가 달라도)."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(SHEAR_FOLDER),
            "spec": {"recipe": "static", "material": MODAL["material"]},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    study_id = created.json()["study_id"]

    body = client.get(f"/api/simulations/studies/{study_id}", headers=member.headers).json()
    assert body["recipe"] == "static"
    assert body["solvers"] == ["ansys"]
    done = [one for one in body["points"] if one["status"] == "done"]
    assert len(done) == 4, [one["status"] for one in body["points"]]
    first = done[0]
    assert first["max_displacement_mm"] > 0
    assert first["max_von_mises_mpa"] > 0
    assert set(first["reactions_n"]) == {"당기는 끝"}
    assert set(first["probes_mm"]) == {"이음 입구 위판", "이음 입구 아래판"}
    assert len(first["probe_vectors_mm"]["이음 입구 위판"]) == 3
    # **같은 자리 두 바디의 차가 미끄럼이다** — 화면과 CSV 가 그 값을 따로 셈하지 않는다.
    slip = first["relative_mm"]["이음 입구 위판 - 이음 입구 아래판"]
    upper = first["probe_vectors_mm"]["이음 입구 위판"]
    lower = first["probe_vectors_mm"]["이음 입구 아래판"]
    assert slip[0] == pytest.approx(upper[0] - lower[0])
    # 모드가 없는 레시피에 모드 칸을 채우지 않는다.
    assert first["frequencies"] == [] and body["tracks"] == []

    listed = client.get("/api/simulations/studies", headers=member.headers).json()
    row = next(one for one in listed if one["study_id"] == study_id)
    assert row["recipe"] == "static" and row["solvers"] == ["ansys"]

    # **CSV 는 화면과 같은 값이다** — 두 길이 따로 계산하면 언젠가 갈린다.
    exported = client.get(
        f"/api/simulations/studies/{study_id}/export.csv", headers=member.headers
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    text = exported.content.decode("utf-8")
    assert text.startswith("\ufeff"), "BOM 이 없으면 Excel 이 한글을 깬다"
    rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))
    head = rows[0]
    assert len(rows) == 1 + len(body["points"])
    assert "반력 당기는 끝 Fx (N)" in head
    assert "측정점 이음 입구 위판 X (mm)" in head
    assert "상대 변위 이음 입구 위판 - 이음 입구 아래판 X (mm)" in head
    column = head.index("최대 변형 (mm)")
    line = next(one for one in rows[1:] if one[-1] == first["simulation_id"])
    assert float(line[column]) == pytest.approx(first["max_displacement_mm"], rel=1e-5)


def test_조화_DOE_비교에_측정점의_봉우리가_실린다(client: TestClient, member: Signed) -> None:
    """조화 DOE 는 **봉우리**를 견준다 — 전체 봉우리와 센서 자리의 봉우리를 따로."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            "path": str(SIDE_SHAKE_FOLDER),
            "spec": {"recipe": "harmonic", "material": MODAL["material"]},
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    study_id = created.json()["study_id"]
    body = client.get(f"/api/simulations/studies/{study_id}", headers=member.headers).json()
    assert body["recipe"] == "harmonic"
    done = [one for one in body["points"] if one["status"] == "done"]
    assert len(done) == 2
    for one in done:
        assert one["peak_hz"] > 0 and one["peak_displacement_mm"] > 0
        assert one["probes_mm"]["측정점"] > 0
        # CAD 가 적은 범위(200~2000 Hz) 안의 봉우리다 — 스펙 기본값(0~2000)이 아니라.
        assert 200 <= one["probe_peaks_hz"]["측정점"] <= 2000

    exported = client.get(
        f"/api/simulations/studies/{study_id}/export.csv", headers=member.headers
    )
    head = next(csv.reader(io.StringIO(exported.content.decode("utf-8").lstrip("\ufeff"))))
    assert "봉우리 주파수 (Hz)" in head
    assert "측정점 측정점 봉우리 진폭 (mm)" in head


def test_이름으로_묶인_옛_스터디도_상세가_열린다(
    client: TestClient, member: Signed, db: Session
) -> None:
    """**목록과 상세가 같은 열쇠로 모은다.** `study_id` 가 없는 옛 가져오기는 목록이 이름으로
    묶는데, 상세가 `study_id` 만 보면 목록에는 있고 열면 404 다."""
    created = client.post(
        "/api/simulations/doe/import",
        json={
            # 다른 시험이 안 쓰는 폴더 — 이미 가져온 점은 다시 만들지 않으므로 겹치면 빈손이다.
            "path": str(DOE_FOLDER.parent / "조건_조건훑기"),
            "spec": MODAL,
            "workspace_slug": member.workspace,
        },
        headers=member.headers,
    )
    assert created.status_code == 201, created.text
    ids = [uuid.UUID(one) for one in created.json()["created"]]
    assert ids, "가져온 점이 없다 — 다른 시험이 같은 폴더를 먼저 가져갔다"
    name = "옛-이름만-있는-스터디"
    for row in db.scalars(select(Simulation).where(Simulation.id.in_(ids))):
        meta = dict(row.source_meta)
        meta.pop("study_id", None)
        meta["study_name"] = name
        row.source_meta = meta
    db.commit()

    listed = client.get("/api/simulations/studies", headers=member.headers).json()
    assert any(one["study_id"] == name for one in listed)
    detail = client.get(f"/api/simulations/studies/{name}", headers=member.headers)
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["points"]) == len(ids)


def test_가져온_DOE_가_비교_목록에_뜬다(client: TestClient, member: Signed) -> None:
    """**스터디를 따로 저장하지 않는다** — 작업 표에서 모은다.

    따로 두면 작업을 지웠을 때 둘이 어긋나고, 그때 어느 쪽이 맞는지 알 수 없다.
    """
    client.post(
        "/api/simulations/doe/import",
        json={"path": str(DOE_FOLDER), "spec": MODAL, "workspace_slug": member.workspace},
        headers=member.headers,
    )
    listed = client.get("/api/simulations/studies", headers=member.headers)
    assert listed.status_code == 200, listed.text
    study = next(one for one in listed.json() if one["name"] == "브래킷_두께훑기")
    assert study["factors"] == ["두께"]
    # 앞 시험들이 같은 폴더를 여러 번 가져왔지만 **점은 세 개뿐이다**(중복을 막는다).
    assert study["points"] == 3
    assert study["done"] == 3  # 인라인 실행기가 끝까지 돌렸다

    detail = client.get(
        f"/api/simulations/studies/{study['study_id']}", headers=member.headers
    )
    assert detail.status_code == 200, detail.text
    points = detail.json()["points"]
    assert [one["params"]["두께"] for one in points] == [6.0, 12.0, 20.0]
    # 비교의 두 축 — 바꾼 값과 그 결과.
    assert all(one["first_elastic_hz"] for one in points)
    # 질량은 **두 번째 축**이다. 지그는 가볍고 단단해야 한다.
    assert all(one["mass_kg"] for one in points)
    # k 차 모드로 견주려면 주파수 목록이 있어야 한다.
    assert len(points[0]["frequencies"]) >= 5


def test_대기_중인_작업은_곧바로_취소된다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """아직 아무도 안 집었다 — 워커를 기다릴 이유가 없다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    canceled = client.post(
        f"/api/simulations/{created.json()['id']}/cancel", headers=member.headers
    )
    assert canceled.status_code == 200, canceled.text
    assert canceled.json()["status"] == "canceled"


def test_끝난_작업은_취소할_것이_없다(client: TestClient, member: Signed) -> None:
    created = _create(client, member, workspace=member.workspace)
    response = client.post(
        f"/api/simulations/{created.json()['id']}/cancel", headers=member.headers
    )
    assert response.status_code == 409
    assert "이미 끝난" in response.json()["error"]["message"]


def test_돌던_작업은_워커가_보고_멈춘다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**워커는 다른 프로세스라** DB 칸으로만 알 수 있다 — 단계 사이와 자식을 기다리는 동안
    그 칸을 본다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    simulation_id = created.json()["id"]
    client.post(f"/api/simulations/{simulation_id}/cancel", headers=member.headers)

    # **그 작업을 콕 집어 돌린다.** `claim_next` 는 가장 오래된 대기 작업을 가져가므로,
    # 스위트를 함께 도는 시험에서는 남이 남긴 작업을 집을 수 있다.
    from app.modules.simulations.models import Simulation

    claimed = db.get(Simulation, uuid.UUID(simulation_id))
    assert claimed is not None
    done = services.execute(db, claimed, worker_id="test-worker")
    assert done.status == "canceled"
    # 실패가 아니므로 「남은 일」 에 안 오른다.
    assert done.error_code is None


def test_취소한_작업은_다시_걸_수_있다(
    client: TestClient, db: Session, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """취소 표시를 안 지우면 다시 건 작업이 첫 확인에서 곧바로 멈춘다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    simulation_id = created.json()["id"]
    client.post(f"/api/simulations/{simulation_id}/cancel", headers=member.headers)

    monkeypatch.setattr(get_settings(), "jobs_inline", True)
    again = client.post(f"/api/simulations/{simulation_id}/retry", headers=member.headers)
    assert again.status_code == 200, again.text
    assert again.json()["status"] == "done"


def test_정리하면_중간_파일이_사라지고_결과는_남는다(
    client: TestClient, db: Session, member: Signed
) -> None:
    """**결과는 남는다.**

    사람이 보는 것(고유진동수 · 모드 그림)은 수십 KB 고, 지우는 것은 `.mechdb` · `.rst` 처럼
    다시 만들 수 있거나 이미 다 읽은 것이다.
    """
    created = _create(client, member, workspace=member.workspace)
    body = created.json()
    kinds_before = {one["kind"] for one in body["artifacts"]}
    assert {"mechdb", "rst", "result_json"} <= kinds_before

    tidied = client.post(f"/api/simulations/{body['id']}/tidy", headers=member.headers)
    assert tidied.status_code == 200, tidied.text
    assert tidied.json()["files"] >= 2

    after = client.get(f"/api/simulations/{body['id']}", headers=member.headers).json()
    kinds_after = {one["kind"] for one in after["artifacts"]}
    # 중간 파일은 행까지 사라진다 — 「DB 에는 있는데 파일이 없는」 상태를 만들지 않는다.
    assert "mechdb" not in kinds_after
    assert "rst" not in kinds_after
    assert {"result_json", "input_step", "spec", "dat", "solve_out"} <= kinds_after


def test_도는_중에는_정리하지_않는다(
    client: TestClient, member: Signed, monkeypatch: pytest.MonkeyPatch
) -> None:
    """그 단계가 읽으려던 파일이 사라진다."""
    monkeypatch.setattr(get_settings(), "jobs_inline", False)
    created = _create(client, member, workspace=member.workspace)
    response = client.post(
        f"/api/simulations/{created.json()['id']}/tidy", headers=member.headers
    )
    assert response.status_code == 409
