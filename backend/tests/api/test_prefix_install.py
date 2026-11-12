"""**접두어 아래 설치**(운영 `/simengbay`) — 그 설치에서만 드러나는 것.

시험은 늘 루트(`/`)로 도는데 운영은 접두어 아래 산다. 그 차이 때문에 **개인 토큰의 쓰기가
범위와 무관하게 전부 막혔다** — `simulations:write` 토큰의 `doe/import` 가 「이 토큰에는 …
범위가 없습니다」(AUTH 106)가 아니라 「개인 토큰으로는 이 경로를 고칠 수 없습니다」(AUTH 105)를
받았다(2026-11-12 운영). 범위 표는 `/api/…` 로 적혀 있는데 판정에 넘긴 경로에는 접두어가
붙어 있었다(`PrefixMiddleware` 가 붙인다 — 정적 파일 마운트가 그것을 요구한다). 같은 까닭으로
접근 로그도 한 줄도 안 남았다. StandardPlatform 은 2026-09-30 · 10-08 에 같은 것을 고쳤다.
"""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.database import SessionLocal
from app.main import create_app
from app.modules.audit.models import AccessLog
from app.shared.auth import scope_path
from app.shared.errors import code
from tests.api.conftest import Signed

PREFIX = "/simengbay"
MODAL: dict[str, Any] = {
    "recipe": "modal",
    "material": {
        "name": "SS400",
        "youngs_modulus_gpa": 200,
        "poisson_ratio": 0.3,
        "density_kg_m3": 7850,
    },
    "modes": 5,
    "mesh": {"element_size_mm": 5},
}
DOE_FOLDER = (
    Path(__file__).resolve().parents[1] / "fixtures" / "doe" / "브래킷_두께훑기-3f9a2177"
)
IMPORT = "/api/simulations/doe/import"


@pytest.fixture
def prefixed(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """접두어 아래 사는 같은 앱 — 설정만 다르다."""
    monkeypatch.setenv("PUBLIC_PATH", PREFIX)
    get_settings.cache_clear()
    app = create_app()
    app.state.session_factory = SessionLocal
    try:
        with TestClient(app) as one:
            yield one
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def _token(client: TestClient, who: Signed, scopes: list[str]) -> dict[str, str]:
    made = client.post(
        "/api/auth/tokens",
        json={"name": f"prefix_{uuid.uuid4().hex[:6]}", "scopes": scopes},
        headers=who.headers,
    )
    assert made.status_code == 201, made.text
    return {"Authorization": f"Bearer {made.json()['token']}"}


def _folder(tmp_path: Path) -> str:
    """가져올 DOE 폴더 — 스터디 id 를 새로 매겨 다른 시험이 가져온 것과 안 겹치게."""
    folder = tmp_path / f"{DOE_FOLDER.name}-{uuid.uuid4().hex[:6]}"
    shutil.copytree(DOE_FOLDER, folder)
    study = json.loads((folder / "study.json").read_text(encoding="utf-8"))
    study["id"] = uuid.uuid4().hex
    (folder / "study.json").write_text(json.dumps(study, ensure_ascii=False), encoding="utf-8")
    get_settings().doe_roots = str(tmp_path)
    return str(folder)


def _error(response: Any) -> str:
    return str((response.json().get("error") or {}).get("code") or "")


def test_접두어_아래에서도_토큰으로_DOE_를_가져온다(
    client: TestClient, member: Signed, prefixed: TestClient, tmp_path: Path
) -> None:
    head = _token(client, member, ["read", "simulations:write"])
    # 접두어를 붙여 부르든(프록시가 그대로 넘김) 빼고 부르든(프록시가 뗌) 같아야 한다.
    for path in (f"{PREFIX}{IMPORT}", IMPORT):
        body = {"path": _folder(tmp_path), "spec": MODAL, "workspace_slug": member.workspace}
        got = prefixed.post(path, json=body, headers=head)
        assert got.status_code == 201, (path, got.status_code, got.text)
        assert got.json()["created"], got.text


def test_범위가_없으면_그렇다고_말한다(
    client: TestClient, member: Signed, prefixed: TestClient, tmp_path: Path
) -> None:
    """**말이 달라지면 사람이 다른 것을 고친다.** 105 는 「어떤 범위로도 안 되는 경로」 고,
    106 은 「이 범위만 켜면 되는 경로」 다."""
    head = _token(client, member, ["read"])
    denied = prefixed.post(
        f"{PREFIX}{IMPORT}",
        json={"path": _folder(tmp_path), "spec": MODAL, "workspace_slug": member.workspace},
        headers=head,
    )
    assert denied.status_code == 403, denied.text
    assert _error(denied) == code("AUTH", 106), denied.text
    assert "simulations:write" in denied.json()["error"]["message"]


def test_범위가_없는_경로는_접두어_아래에서도_막는다(
    client: TestClient, member: Signed, prefixed: TestClient
) -> None:
    """부서 만들기에는 쓰기 범위가 없다 — 105 가 맞는 자리다."""
    head = _token(client, member, ["read", "simulations:write"])
    denied = prefixed.post(
        f"{PREFIX}/api/workspaces", json={"slug": "sneaky", "name": "몰래"}, headers=head
    )
    assert denied.status_code == 403, denied.text
    assert _error(denied) == code("AUTH", 105), denied.text


def test_접두어_아래에서도_접근_로그가_남는다(
    client: TestClient, member: Signed, prefixed: TestClient, tmp_path: Path
) -> None:
    """`/api/` 로 시작하는지만 보던 접근 로그가 접두어 설치에서는 한 줄도 안 남겼다. 남길 때는
    접두어를 뗀 경로로."""
    head = _token(client, member, ["read", "simulations:write"])

    def count() -> int:
        with SessionLocal() as db:
            return int(
                db.scalar(
                    select(func.count()).select_from(AccessLog).where(AccessLog.path == IMPORT)
                )
                or 0
            )

    before = count()
    got = prefixed.post(
        f"{PREFIX}{IMPORT}",
        json={"path": _folder(tmp_path), "spec": MODAL, "workspace_slug": member.workspace},
        headers=head,
    )
    assert got.status_code == 201, got.text
    assert count() == before + 1


def _request(path: str, root_path: str) -> Request:
    return Request({"type": "http", "method": "POST", "path": path, "root_path": root_path})


def test_범위_표와_견줄_경로는_접두어를_떼고_라우팅이_보는_그대로다() -> None:
    assert scope_path(_request(f"{PREFIX}{IMPORT}", PREFIX)) == IMPORT
    assert scope_path(_request(PREFIX, PREFIX)) == "/"
    assert scope_path(_request(IMPORT, "")) == IMPORT
    # 이름이 접두어로 시작할 뿐인 다른 경로는 떼지 않는다.
    assert scope_path(_request(f"{PREFIX}x/api", PREFIX)) == f"{PREFIX}x/api"
    # `url.path` 는 `%3F`(?) 에서 잘려 앞쪽만 남는다 — 라우팅이 보는 경로를 그대로 쓴다.
    assert scope_path(_request("/api/simulations?/retry", "")) == "/api/simulations?/retry"
