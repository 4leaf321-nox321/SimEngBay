"""온톨로지 수신 — **받는 쪽 규칙**(Standard Platform 연동 지침서 §4.2)을 하나씩 본다.

가짜 SP(`tests/ontology_fake.py`)가 지침서의 약속대로 답한다. 규칙을 어긴 수신은 오류 없이
그럴듯하게 돈다 — 시각을 앞서 옮기면 그 사이 행이 새고, 무덤을 안 읽으면 지운 것이 되살아나고,
전량을 대조하지 않으면 사라진 것을 영영 들고 있는다. 그래서 규칙마다 시험이 하나다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.modules.ontology import sync
from app.modules.ontology.models import (
    OntologyObject,
    OntologyRelation,
    OntologySyncRun,
    OntologyType,
)
from tests.ontology_fake import BASE, TOKEN, FakeCore, _error, materials_and_vendors

NOW = datetime(2026, 10, 13, 1, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def clean(db: Session) -> Iterator[None]:
    for table in (OntologyRelation, OntologyObject, OntologySyncRun, OntologyType):
        db.execute(delete(table))
    db.commit()
    yield


def _run(
    db: Session,
    core: FakeCore,
    *,
    full: bool = False,
    now: datetime = NOW,
    full_every: timedelta | None = timedelta(days=7),
    client: sync.CoreClient | None = None,
) -> OntologySyncRun:
    record = OntologySyncRun(trigger="script", full=full)
    db.add(record)
    db.commit()
    sync.run(db, client or core.client(), record, now=now, full=full, full_every=full_every)
    db.commit()
    return record


def _client(
    core: FakeCore, wrap: Callable[[httpx.Request], httpx.Response | None]
) -> sync.CoreClient:
    """가짜 SP 앞에 끼워 몇 번의 답을 갈아 낀다 — `None` 이면 SP 가 답한다."""

    def handler(request: httpx.Request) -> httpx.Response:
        return wrap(request) or core.handler(request)

    return sync.CoreClient(
        BASE, TOKEN, transport=httpx.MockTransport(handler), sleep=lambda _: None
    )


def _objects(db: Session, slug: str) -> dict[str, OntologyObject]:
    db.expire_all()
    return {
        one.key: one
        for one in db.scalars(select(OntologyObject).where(OntologyObject.type_slug == slug))
    }


def _edges(db: Session) -> set[tuple[str, str, str, str]]:
    return {
        (one.src_key, one.relation, one.dst_key, one.dst_type)
        for one in db.scalars(select(OntologyRelation))
    }


def test_처음엔_카탈로그대로_타입을_만들고_전량을_받는다(db: Session) -> None:
    core = materials_and_vendors()
    record = _run(db, core)

    assert record.status == "ok" and record.revision == "1-aaaa"
    material = db.get(OntologyType, "material")
    assert material is not None
    assert material.label == "재료" and material.relations == ["supplied_by"]
    assert [one["key"] for one in material.properties] == ["density", "supplier"]
    assert material.source_count == 3
    # **서버가 준 as_of 를 그대로** 다음 since 로 쓴다(규칙 1).
    assert material.rows_as_of == core.now() and material.relations_as_of == core.now()
    rows = _objects(db, "material")
    assert set(rows) == {"SS400", "AL6061", "SUS304"}
    assert rows["SS400"].properties == {"density": 7850, "supplier": "ACME-001"}
    assert all(one.active for one in rows.values())
    assert _edges(db) == {
        ("SS400", "supplied_by", "ACME-001", "vendor"),
        ("AL6061", "supplied_by", "HAN-002", "vendor"),
    }
    assert record.summary["types"]["material"]["created"] == 3
    # 처음 만든 것은 「되살림」 이 아니다.
    assert "reactivated" not in record.summary["types"]["material"]


def test_다음_수신은_지난_as_of_부터_바뀐_것만_받는다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)
    before = core.now()
    core.put("material", "SS400", "일반구조용강", properties={"density": 7860})
    core.calls.clear()

    record = _run(db, core)

    asked = [params for path, params in core.calls if path == "/api/core/material"]
    assert asked == [{"limit": "500", "since": before}]
    assert _objects(db, "material")["SS400"].properties == {"density": 7860}
    assert record.summary["types"]["material"]["rows"] == 1
    # 바뀐 것이 없는 타입도 다시 물었고 받은 것은 없다 — 같은 수신을 한 번 더 해도 그대로다.
    assert "rows" not in record.summary["types"]["vendor"]


def test_쪽이_남은_채_막히면_시각을_옮기지_않고_받다_만_것을_맺지_않는다(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`next` 가 남았는데 시각을 옮기면 남은 쪽을 영영 안 받는다(규칙 2). 받다 만 쪽도 맺지
    않는다 — 반쯤 받은 상태가 정본처럼 보이면 안 된다."""
    monkeypatch.setattr(sync, "PAGE_SIZE", 2)
    core = materials_and_vendors()
    _run(db, core)
    since = db.get(OntologyType, "material").rows_as_of  # type: ignore[union-attr]
    for key, density in (("SS400", 1), ("AL6061", 2), ("SUS304", 3)):
        core.put("material", key, key, properties={"density": density})

    def second_page_fails(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == "/api/core/material" and request.url.params.get("cursor"):
            return _error(503, "APP-SERVER-0001", "잠시 쉬는 중입니다.")
        return None

    record = _run(db, core, client=_client(core, second_page_fails))

    assert record.status == "partial"
    material = db.get(OntologyType, "material")
    assert material is not None and material.rows_as_of == since
    assert "서버 오류가 계속됩니다" in material.last_error
    assert _objects(db, "material")["SS400"].properties == {
        "density": 7850,
        "supplier": "ACME-001",
    }
    # 다른 타입은 그대로 받았다 — 한 타입의 문제로 전부가 멈추지 않는다.
    assert record.summary["types"]["vendor"].get("error") is None

    # 다음 수신은 같은 자리부터 끝까지 받는다.
    again = _run(db, core)
    assert again.status == "ok"
    assert {
        key: one.properties["density"] for key, one in _objects(db, "material").items()
    } == {
        "SS400": 1,
        "AL6061": 2,
        "SUS304": 3,
    }


def test_지운_것_합친_것_이름을_바꾼_것_안_보이게_된_것을_읽는다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)
    before = _objects(db, "material")
    sus_id = before["SUS304"].id

    core.delete("material", "AL6061", merged_into="SS400")
    core.rename("material", "SUS304", "SUS304L")
    core.hide("vendor", "HAN-002")
    record = _run(db, core)

    rows = _objects(db, "material")
    # 지우지 않고 끈다 — 합쳐진 곳을 적는다(규칙 4).
    assert rows["AL6061"].active is False
    assert (rows["AL6061"].removed_reason, rows["AL6061"].merged_into) == ("merged", "SS400")
    # 그 객체를 끝점으로 하는 선은 우리가 끊는다(규칙 9).
    assert ("AL6061", "supplied_by", "HAN-002", "vendor") not in _edges(db)
    # 이름을 바꾸면 같은 행의 키를 옮긴다 — 둘이 되지 않는다.
    assert "SUS304" not in rows and rows["SUS304L"].id == sus_id
    assert rows["SUS304L"].previous_keys == ["SUS304"]
    # 안 보이게 된 것은 가진 값을 두고 끄기만 한다.
    vendors = _objects(db, "vendor")
    assert vendors["HAN-002"].active is False and vendors["HAN-002"].removed_reason == "hidden"
    assert vendors["HAN-002"].label == "한강금속"
    summary = record.summary["types"]
    assert summary["material"]["renamed"] == 1 and summary["material"]["deactivated"] == 1

    # 지운 것이 같은 key 로 다시 오면 되살린다(규칙 8).
    core.put("material", "AL6061", "알루미늄 6061", properties={"density": 2710})
    revived = _run(db, core)
    rows = _objects(db, "material")
    assert rows["AL6061"].active is True and rows["AL6061"].removed_reason == ""
    assert rows["AL6061"].merged_into is None
    assert revived.summary["types"]["material"]["reactivated"] == 1


def test_공개를_내린_타입은_그_타입만_멈추고_받아_둔_것은_남긴다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)

    def vendor_unpublished(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == "/api/core/vendor":
            return _error(404, "APP-CORE-0001", "코어로 공개되지 않은 타입입니다: vendor")
        return None

    record = _run(db, core, client=_client(core, vendor_unpublished))
    vendor = db.get(OntologyType, "vendor")
    assert vendor is not None and vendor.published is False
    assert "공개되지 않은 타입" in vendor.last_error
    assert (
        record.status == "partial" and record.summary["types"]["material"].get("error") is None
    )
    assert len(_objects(db, "vendor")) == 2

    # 카탈로그에서 빠지면 공개 안 됨으로 — 받아 둔 것은 남긴다.
    del core.types["vendor"]
    _run(db, core)
    vendor = db.get(OntologyType, "vendor")
    assert vendor is not None and vendor.published is False
    assert all(one.active for one in _objects(db, "vendor").values())


def test_커서를_못_읽으면_커서_없이_지난_시각부터_다시_받는다(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync, "PAGE_SIZE", 2)
    core = materials_and_vendors()
    failed: list[str] = []

    def cursor_lost_once(request: httpx.Request) -> httpx.Response | None:
        if request.url.params.get("cursor") and not failed:
            failed.append(str(request.url))
            return _error(404, "APP-CORE-0002", "커서를 읽을 수 없습니다.")
        return None

    record = _run(db, core, client=_client(core, cursor_lost_once))
    assert failed and record.status == "ok"
    assert set(_objects(db, "material")) == {"SS400", "AL6061", "SUS304"}


def test_전량_대조는_안_온_것을_끄고_절반이_넘으면_끄지_않는다(db: Session) -> None:
    """`since` 없이 받으면 지운 것은 안 온다 — 끝까지 받은 뒤 이번에 안 온 것을 끈다(규칙 7).
    한꺼번에 절반 넘게 안 오면 토큰의 부서 · 공개 범위가 바뀐 것이니 끄지 않는다."""
    core = materials_and_vendors()
    _run(db, core)
    del core.rows["material"]["SUS304"]  # 무덤 없이 사라졌다(토큰 주인의 소속이 줄었다).
    record = _run(db, core, full=True)
    rows = _objects(db, "material")
    assert rows["SUS304"].active is False and rows["SUS304"].removed_reason == "absent"
    assert record.summary["types"]["material"]["full"] is True

    core.add_type("part", "부품")
    for index in range(12):
        core.put("part", f"P-{index:02d}", f"부품 {index}")
    _run(db, core)
    for index in range(7):
        del core.rows["part"][f"P-{index:02d}"]
    guarded = _run(db, core, full=True)
    assert guarded.status == "partial"
    assert "절반이 넘어 끄지 않았습니다" in guarded.summary["types"]["part"]["error"]
    assert all(one.active for one in _objects(db, "part").values())


def test_주기가_되면_처음부터_전량을_받아_대조한다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)
    core.calls.clear()
    _run(db, core, now=NOW + timedelta(days=8), full_every=timedelta(days=7))
    asked = [params for path, params in core.calls if path == "/api/core/material"]
    assert asked == [{"limit": "500"}]  # since 없이 — 전량이다.


def test_선이_처음부터_다시를_말하면_전량을_받고_안_온_선을_끊는다(db: Session) -> None:
    """끊긴 선의 기록은 한동안만 있다 — 오래 안 받아 갔으면 SP 가 「처음부터 다시」 를 말한다.
    빈 쪽을 「바뀐 것 없음」 으로 읽으면 끊긴 선을 영영 들고 있는다."""
    core = materials_and_vendors()
    _run(db, core)
    core.forget_edge("material", "AL6061", "supplied_by", "HAN-002", "vendor")
    core.reset_relations.add("material")
    record = _run(db, core)
    assert _edges(db) == {("SS400", "supplied_by", "ACME-001", "vendor")}
    report = record.summary["types"]["material"]
    assert report["relations_full"] is True and report["relations_removed"] == 1


def test_끊긴_선은_지운다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)
    core.unlink("material", "SS400", "supplied_by", "ACME-001", "vendor")
    core.link("material", "SUS304", "supplied_by", "ACME-001", "vendor")
    _run(db, core)
    assert _edges(db) == {
        ("AL6061", "supplied_by", "HAN-002", "vendor"),
        ("SUS304", "supplied_by", "ACME-001", "vendor"),
    }


def test_끈_타입은_받지_않는다(db: Session) -> None:
    core = materials_and_vendors()
    _run(db, core)
    vendor = db.get(OntologyType, "vendor")
    assert vendor is not None
    vendor.enabled = False
    db.commit()
    core.calls.clear()
    record = _run(db, core)
    assert not any(path.startswith("/api/core/vendor") for path, _ in core.calls)
    assert "vendor" not in record.summary["types"]


def test_정의_판이_바뀌면_적는다(db: Session) -> None:
    core = materials_and_vendors()
    first = _run(db, core)
    first.status = "ok"
    db.commit()
    core.revision = "2-bbbb"
    record = _run(db, core)
    assert record.revision == "2-bbbb" and record.summary.get("revision_changed") is True


def test_토큰이_틀리면_무엇을_고칠지_말한다(db: Session) -> None:
    core = materials_and_vendors()
    record = OntologySyncRun(trigger="script")
    db.add(record)
    db.commit()
    with pytest.raises(sync.CoreError) as failure:
        sync.run(db, core.client(token="wrong"), record, now=NOW)
    assert "core:read" in failure.value.message and failure.value.request_id == "req-1"


def test_주소는_api_든_api_core_든_받는다() -> None:
    assert sync.core_base("https://sp.example.com/api") == "https://sp.example.com/api/core/"
    assert (
        sync.core_base("https://sp.example.com/api/core/")
        == "https://sp.example.com/api/core/"
    )


def test_타이머는_차례가_됐을_때만_받는다(db: Session) -> None:
    """5분마다 묻지만 받는 것은 주기(`ONTOLOGY_SYNC_MINUTES`)마다다. 0 이면 화면으로만."""
    from app.config import get_settings
    from app.modules.ontology import services

    settings = get_settings().model_copy(
        update={
            "ontology_source_url": BASE,
            "ontology_source_token": TOKEN,
            "ontology_sync_minutes": 60,
        }
    )
    now = datetime.now(UTC)
    assert services.due(db, settings, now)  # 한 번도 안 받았다.
    db.add(OntologySyncRun(status="ok", finished_at=now - timedelta(minutes=10)))
    db.commit()
    assert not services.due(db, settings, now)
    assert services.due(db, settings, now + timedelta(minutes=51))
    manual_only = settings.model_copy(update={"ontology_sync_minutes": 0})
    assert services.next_due(db, manual_only) is None
    unconfigured = settings.model_copy(update={"ontology_source_token": ""})
    assert services.next_due(db, unconfigured) is None
