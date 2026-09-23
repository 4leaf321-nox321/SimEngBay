"""해석 작업 — 걸고, 돌고, 산출물을 받고, **못 볼 것은 못 본다.**

실행기는 fake 다(시험 `.env` 기본). `JOBS_INLINE` 을 켜서 요청 안에서 네 단계가 다 돈다 —
워커와
같은 `services.execute` 를 지나므로 상태 기계 · 산출물 등록 · 실패 기록이 여기서 검증된다.
"""

from __future__ import annotations

import io
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.stages import StageContext, StageFailure, StageResult
from app.modules.simulations import services
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


def test_실행기가_없는_레시피는_거절한다(client: TestClient, member: Signed) -> None:
    static = {
        "recipe": "static",
        "material": MATERIAL,
        "constraints": [{"region": "fixed_base"}],
    }
    response = _create(client, member, spec=static, workspace=member.workspace)
    assert response.status_code == 400
    assert "static" in response.json()["error"]["message"]


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


def test_폴더가_아니면_무엇이_없는지_말한다(client: TestClient, member: Signed) -> None:
    got = client.get("/api/simulations/doe/preview?path=/tmp", headers=member.headers)
    assert got.status_code == 400
    assert "manifest.csv" in got.json()["error"]["message"]


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
    assert one["source_meta"]["recipe_digest"].startswith("sha256:")
    # 점마다의 영역 지문이 함께 실린다 — 구속을 걸 수 있다.
    assert "topology" in {artifact["kind"] for artifact in one["artifacts"]}
    assert "두께 6" in one["name"]


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
