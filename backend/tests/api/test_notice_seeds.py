"""판마다의 업데이트 안내 — **초안으로 들어오고, 같은 키는 두 번 안 들어오고, 지운 초안은 안
되살아난다**(CompCore · MatNexus 와 같은 길, 2026-11-28).

새 기능은 코드와 함께 도착하는데 알리는 글은 사람이 따로 써야 했다. 씨앗이 초안으로 들어오면
시스템 관리자가 읽고 발행한다 — 자동 발행하지 않는다(배포한 사람이 첫 독자다). 발행한 배포
안내는 그 판의 날짜에 선다.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.notices.models import Notice, NoticeSeedKey
from tests.api.conftest import Signed

BACKEND = Path(__file__).resolve().parents[2]
SEEDS = BACKEND / "seeds" / "notices"


@pytest.fixture(autouse=True)
def _empty_board(db: Session) -> None:
    """**시험마다 빈 게시판** — 이 파일의 시험은 「목록이 정확히 이것」 을 본다. 읽음은 FK 가
    함께 지운다."""
    db.execute(delete(Notice))
    db.execute(delete(NoticeSeedKey))
    db.commit()


def _script() -> Any:
    spec = importlib.util.spec_from_file_location(
        "import_notices", BACKEND / "scripts" / "import_notices.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["import_notices"] = module
    spec.loader.exec_module(module)
    return module


def test_씨앗이_초안으로_한_번만_들어오고_관리자만_본다(
    client: TestClient, db: Session, admin: Signed, member: Signed, tmp_path: Path
) -> None:
    script = _script()
    (tmp_path / "2026-11-28-v0.38.0.md").write_text(
        "# v0.38.0 업데이트 — 소성 해석\n\n■ 새로 생긴 것\n- 소성 재료\n- 하중 단계\n",
        encoding="utf-8",
    )
    (tmp_path / "빈-것.md").write_text("# 제목만\n", encoding="utf-8")  # 본문 없음 — 건너뛴다

    assert script.run(db, tmp_path) == ["2026-11-28-v0.38.0"]
    assert script.run(db, tmp_path) == []  # 두 번째는 아무것도 안 넣는다
    assert script.plan(db, tmp_path) == []

    [row] = db.scalars(select(Notice).where(Notice.seed_key.is_not(None))).all()
    assert row.title == "v0.38.0 업데이트 — 소성 해석"
    assert row.body == "■ 새로 생긴 것\n- 소성 재료\n- 하중 단계"
    assert row.published_at is None and row.is_popup is False and row.level == "info"
    assert row.author_id is None

    # 관리자는 초안을 보고(배포 안내로), 일반 사용자는 못 본다.
    listed = client.get("/api/notices?include_drafts=true", headers=admin.headers).json()
    [seen] = [one for one in listed if one["title"] == "v0.38.0 업데이트 — 소성 해석"]
    assert seen["from_release"] is True and seen["published_at"] is None
    assert client.get("/api/notices", headers=member.headers).json() == []
    assert client.get("/api/notices?include_drafts=true", headers=member.headers).json() == []

    # 운영에서 고친 글은 안 덮인다 — 같은 키의 파일 내용이 바뀌어도.
    (tmp_path / "2026-11-28-v0.38.0.md").write_text(
        "# 바뀐 제목\n\n다른 본문\n", encoding="utf-8"
    )
    assert script.run(db, tmp_path) == []
    db.expire_all()
    kept = db.scalar(select(Notice).where(Notice.seed_key == "2026-11-28-v0.38.0"))
    assert kept is not None and kept.title == "v0.38.0 업데이트 — 소성 해석"


def test_지운_초안은_다음_배포에_되살아나지_않는다(
    client: TestClient, db: Session, admin: Signed, tmp_path: Path
) -> None:
    script = _script()
    (tmp_path / "2026-11-15-v0.9.0.md").write_text("# 지울 것\n\n- 본문\n", encoding="utf-8")
    assert script.run(db, tmp_path) == ["2026-11-15-v0.9.0"]
    assert db.get(NoticeSeedKey, "2026-11-15-v0.9.0") is not None

    notice = db.scalar(select(Notice).where(Notice.seed_key == "2026-11-15-v0.9.0"))
    assert notice is not None
    gone = client.delete(f"/api/notices/{notice.id}", headers=admin.headers)
    assert gone.status_code == 204, gone.text
    db.expire_all()

    assert script.plan(db, tmp_path) == []
    assert script.run(db, tmp_path) == []
    assert db.scalar(select(Notice).where(Notice.seed_key == "2026-11-15-v0.9.0")) is None

    # 기억 밖에서 들어온 줄(공지 행만 있다)도 두 번 넣지 않는다.
    db.add(Notice(title="옛 것", body="본문", seed_key="2026-11-15-옛-것"))
    db.commit()
    (tmp_path / "2026-11-15-옛-것.md").write_text("# 옛 것\n\n본문\n", encoding="utf-8")
    assert script.plan(db, tmp_path) == []


def test_만든_시각은_판의_날짜이고_같은_날은_판_번호_순이다(
    db: Session, tmp_path: Path
) -> None:
    """첫 배포에 수십 판이 한꺼번에 들어와도 게시판이 버전 순으로 선다 — 넣은 순간으로 두면
    전부 같은 시각이라 차례가 없다. v0.10.0 은 v0.9.0 뒤다(문자 순이 아니다)."""
    script = _script()
    for key in (
        "2026-11-14-v0.10.0",
        "2026-11-14-v0.9.0",
        "2026-11-14-v0.9.1",
        "2026-11-13-v0.8.0",
    ):
        (tmp_path / f"{key}.md").write_text(f"# {key}\n\n- 본문\n", encoding="utf-8")
    script.run(db, tmp_path)
    rows = {
        one.seed_key: one.created_at
        for one in db.scalars(select(Notice).where(Notice.seed_key.is_not(None)))
    }
    order = sorted(rows, key=lambda key: rows[key])
    assert order == [
        "2026-11-13-v0.8.0",
        "2026-11-14-v0.9.0",
        "2026-11-14-v0.9.1",
        "2026-11-14-v0.10.0",
    ]
    # 한국 시각으로 그 날짜다(자정 UTC 면 화면에서 날짜가 어긋난다).
    first = rows["2026-11-14-v0.9.0"].astimezone(script.KST)
    assert (first.year, first.month, first.day, first.hour) == (2026, 11, 14, 9)
    assert rows["2026-11-14-v0.9.1"] - rows["2026-11-14-v0.9.0"] == timedelta(minutes=1)


def test_일괄_발행은_배포_안내만이고_손으로_쓴_초안은_하나씩_지금으로_발행한다(
    client: TestClient, db: Session, admin: Signed, member: Signed, tmp_path: Path
) -> None:
    script = _script()
    # 판의 날짜는 지금보다 앞이어야 손으로 쓴 공지(지금 발행)가 맨 위에 선다.
    for key in ("2026-10-03-v0.2.0", "2026-11-20-v0.38.0"):
        (tmp_path / f"{key}.md").write_text(f"# {key}\n\n- 본문\n", encoding="utf-8")
    script.run(db, tmp_path)
    made = client.post(
        "/api/notices",
        headers=admin.headers,
        json={"title": "점검 안내", "body": "내일 점검", "publish": False},
    )
    assert made.status_code == 201, made.text

    # 하나만 발행 — 그 판의 날짜(만든 시각)에 선다.
    old = db.scalar(select(Notice).where(Notice.seed_key == "2026-10-03-v0.2.0"))
    assert old is not None
    one = client.post(f"/api/notices/{old.id}/publish", headers=admin.headers)
    assert one.status_code == 200, one.text
    assert one.json()["published_at"] == one.json()["created_at"]
    denied = client.post(f"/api/notices/{old.id}/publish", headers=member.headers)
    assert denied.status_code == 403

    # 일괄 발행은 배포 안내 초안만 — 손으로 쓰다 둔 「점검 안내」 는 빠진다.
    rest = client.post("/api/notices/publish-drafts", headers=admin.headers)
    assert rest.status_code == 200 and rest.json() == {"published": 1}
    shown = client.get("/api/notices", headers=member.headers).json()
    assert [row["title"] for row in shown] == ["2026-11-20-v0.38.0", "2026-10-03-v0.2.0"]
    drafts = client.get("/api/notices?include_drafts=true", headers=admin.headers).json()
    hand = next(row for row in drafts if row["title"] == "점검 안내")
    assert hand["published_at"] is None and hand["from_release"] is False

    # 손 글 초안은 하나씩 — 발행 시각은 지금이라 맨 위에 선다.
    later = client.post(f"/api/notices/{hand['id']}/publish", headers=admin.headers)
    assert later.status_code == 200, later.text
    assert later.json()["published_at"] > later.json()["created_at"]
    shown = client.get("/api/notices", headers=member.headers).json()
    assert shown[0]["title"] == "점검 안내"


def test_실린_씨앗은_전부_읽히고_판마다_하나이며_지금_판도_있다() -> None:
    """저장소의 씨앗 파일이 제목 · 본문을 갖는다 — 배포에서 처음 터지면 늦다. 이름은
    `<날짜>-v<판>` 이고, 첫 줄은 `# v<판> 업데이트 — …`, 같은 판이 두 번 실리지 않는다. **지금
    판(pyproject)의 안내가 있어야 한다** — 판을 내면서 안내를 빠뜨리지 않게."""
    script = _script()
    files = sorted(SEEDS.glob("*.md"))
    assert files, "안내 씨앗이 하나도 없다"
    seen: set[str] = set()
    for path in files:
        title, body = script.read_seed(path)
        assert title and body, path.name
        found = re.fullmatch(r"\d{4}-\d{2}-\d{2}-v(\d+\.\d+\.\d+)", path.stem)
        assert found, path.name
        version = found.group(1)
        assert version not in seen, path.name
        seen.add(version)
        assert re.match(rf"v{re.escape(version)} 업데이트 — \S", title), path.name
    current = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    assert current["project"]["version"] in seen, "지금 판의 업데이트 안내가 없다"
