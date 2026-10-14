"""온톨로지 라우터 — 읽기는 누구나, 수신 · 「받나」 는 시스템 관리자.

**받아 온 것을 여기서 고치는 길은 없다**(지침서 §12-A 2 — 공개한 쪽이 이긴다). 바뀌는 길은
Standard Platform 에서 고치고 다음 수신을 기다리는 것 하나다.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.modules.accounts.models import User
from app.modules.ontology import services
from app.modules.ontology.models import (
    OntologyObject,
    OntologyRelation,
    OntologySyncRun,
    OntologyType,
)
from app.modules.ontology.schemas import (
    OntologyEdgeOut,
    OntologyObjectDetailOut,
    OntologyObjectOut,
    OntologyPropertyOut,
    OntologyRunOut,
    OntologyStatusOut,
    OntologySyncRequest,
    OntologyTypeOut,
    OntologyTypePatch,
)
from app.shared.auth import current_user, require_system_admin
from app.shared.pagination import Page, clamp_limit

router = APIRouter(prefix="/ontology", tags=["ontology"])


def _run_out(db: Session, record: OntologySyncRun) -> OntologyRunOut:
    actor = db.get(User, record.actor_id) if record.actor_id else None
    return OntologyRunOut(
        id=record.id,
        trigger=record.trigger,
        full=record.full,
        status=record.status,
        revision=record.revision,
        summary=services.run_summary(record),
        error=record.error,
        actor_name=(actor.display_name or actor.email) if actor else None,
        started_at=record.started_at,
        finished_at=record.finished_at,
    )


def _type_out(kind: OntologyType, counts: dict[str, int]) -> OntologyTypeOut:
    return OntologyTypeOut(
        slug=kind.slug,
        label=kind.label,
        properties=[
            OntologyPropertyOut.model_validate(
                {
                    "key": str(one.get("key") or ""),
                    "label": str(one.get("label") or ""),
                    "data_type": str(one.get("data_type") or ""),
                    "unit": one.get("unit"),
                    "enum_options": one.get("enum_options"),
                    "ref_type_slug": one.get("ref_type_slug"),
                    "multi": one.get("multi"),
                }
            )
            for one in kind.properties or []
            if one.get("key")
        ],
        relations=list(kind.relations or []),
        source_count=kind.source_count,
        active_count=counts.get("active", 0),
        inactive_count=counts.get("inactive", 0),
        relation_count=counts.get("relations", 0),
        published=kind.published,
        enabled=kind.enabled,
        synced_at=kind.synced_at,
        full_at=kind.full_at,
        last_error=kind.last_error,
    )


def _object_out(
    row: OntologyObject, ref_labels: dict[str, str] | None = None
) -> OntologyObjectOut:
    return OntologyObjectOut(
        type_slug=row.type_slug,
        key=row.key,
        label=row.label,
        status=row.status,
        properties=dict(row.properties or {}),
        active=row.active,
        removed_reason=row.removed_reason,
        merged_into=row.merged_into,
        previous_keys=list(row.previous_keys or []),
        source_updated_at=row.source_updated_at,
        synced_at=row.synced_at,
        ref_labels=ref_labels or {},
    )


@router.get("/status", response_model=OntologyStatusOut)
def status(
    _: User = Depends(current_user), db: Session = Depends(get_db)
) -> OntologyStatusOut:
    busy = services.running(db)
    last = services.last_finished(db)
    revision = db.scalar(
        select(OntologySyncRun.revision)
        .where(OntologySyncRun.revision != "")
        .order_by(OntologySyncRun.started_at.desc())
        .limit(1)
    )
    settings = get_settings()
    return OntologyStatusOut(
        configured=services.configured(settings),
        source=services.source_shown(settings),
        sync_minutes=settings.ontology_sync_minutes,
        full_days=settings.ontology_full_days,
        next_due_at=services.next_due(db, settings),
        running=_run_out(db, busy) if busy else None,
        last_run=_run_out(db, last) if last else None,
        revision=revision or "",
        types=int(db.scalar(select(func.count()).select_from(OntologyType)) or 0),
        objects=int(
            db.scalar(
                select(func.count())
                .select_from(OntologyObject)
                .where(OntologyObject.active.is_(True))
            )
            or 0
        ),
        relations=int(db.scalar(select(func.count()).select_from(OntologyRelation)) or 0),
    )


@router.get("/types", response_model=list[OntologyTypeOut])
def list_types(
    _: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[OntologyTypeOut]:
    counts = services.type_counts(db)
    kinds = db.scalars(select(OntologyType).order_by(OntologyType.label, OntologyType.slug))
    return [_type_out(kind, counts.get(kind.slug, {})) for kind in kinds]


@router.patch("/types/{slug}", response_model=OntologyTypeOut)
def patch_type(
    slug: str,
    payload: OntologyTypePatch,
    _: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> OntologyTypeOut:
    """「받나」 를 켜고 끈다. 끄면 받아 둔 것은 남기고 다음 수신부터 안 받는다."""
    kind = services.get_type(db, slug)
    kind.enabled = payload.enabled
    db.commit()
    return _type_out(kind, services.type_counts(db).get(slug, {}))


@router.get("/types/{slug}/objects", response_model=Page[OntologyObjectOut])
def list_objects(
    slug: str,
    q: str = Query(default="", max_length=200),
    include_inactive: bool = Query(default=False),
    limit: int | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Page[OntologyObjectOut]:
    kind = services.get_type(db, slug)
    size = clamp_limit(limit)
    rows, total = services.objects(
        db, slug, q=q, include_inactive=include_inactive, limit=size, offset=offset
    )
    found = services.ref_labels(db, kind, rows)
    return Page[OntologyObjectOut](
        items=[_object_out(row, services.row_ref_labels(kind, row, found)) for row in rows],
        total=total,
        limit=size,
        offset=offset,
    )


@router.get("/types/{slug}/object", response_model=OntologyObjectDetailOut)
def get_object(
    slug: str,
    key: str = Query(min_length=1, max_length=255),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> OntologyObjectDetailOut:
    """객체 하나와 그 선. `key` 는 쿼리로 받는다 — 식별자에 `/` 가 들어 있을 수 있다."""
    kind = services.get_type(db, slug)
    row = services.one_object(db, slug, key)
    refs = services.row_ref_labels(kind, row, services.ref_labels(db, kind, [row]))
    outgoing, incoming = services.edges(db, slug, key)
    pairs = {(one.dst_type, one.dst_key) for one in outgoing} | {
        (one.src_type, one.src_key) for one in incoming
    }
    labels = services.labels_for(db, pairs)

    def edge(one: OntologyRelation) -> OntologyEdgeOut:
        return OntologyEdgeOut(
            relation=one.relation,
            src_type=one.src_type,
            src_key=one.src_key,
            src_label=labels.get((one.src_type, one.src_key)),
            dst_type=one.dst_type,
            dst_key=one.dst_key,
            dst_label=labels.get((one.dst_type, one.dst_key)),
            evidence_note=one.evidence_note,
            properties=dict(one.properties or {}),
        )

    return OntologyObjectDetailOut(
        **_object_out(row, refs).model_dump(),
        outgoing=[edge(one) for one in outgoing],
        incoming=[edge(one) for one in incoming],
    )


@router.get("/runs", response_model=list[OntologyRunOut])
def list_runs(
    limit: int | None = Query(default=None),
    _: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[OntologyRunOut]:
    rows = db.scalars(
        select(OntologySyncRun)
        .order_by(OntologySyncRun.started_at.desc())
        .limit(clamp_limit(limit))
    )
    return [_run_out(db, row) for row in rows]


@router.post("/sync", response_model=OntologyRunOut, status_code=202)
def start_sync(
    payload: OntologySyncRequest,
    user: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> OntologyRunOut:
    """「지금 받기」 — 기록을 열고 실을 띄운다. 끝나기를 기다리지 않는다(화면이 기록을
    본다)."""
    record = services.start(db, trigger="manual", actor=user, full=payload.full)
    run_id = record.id
    services.spawn(lambda: services.execute(run_id))
    db.refresh(record)
    return _run_out(db, record)
