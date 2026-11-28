"""공지 라우터 — 읽기는 누구나, 쓰기는 시스템 관리자.

판마다 업데이트 안내가 배포에 실려 와 **초안**으로 들어온다(`scripts/import_notices.py`).
관리자가 읽고 발행한다(`publish` · 「배포 안내 초안 모두 발행」). **배포 안내의 발행 시각은
그 판의 날짜다** — 첫 배포에 수십 판이 한꺼번에 들어와도 판 순서대로 선다(CompCore 와 같다).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.modules.accounts.models import User
from app.modules.notices.models import Notice, NoticeRead
from app.modules.notices.schemas import NoticeOut, NoticePublishedOut, NoticeWriteRequest
from app.shared.auth import current_user, require_system_admin
from app.shared.errors import NotFound, code

router = APIRouter(prefix="/notices", tags=["notices"])


def _out(db: Session, notice: Notice, user: User) -> NoticeOut:
    author = db.get(User, notice.author_id) if notice.author_id else None
    read = db.scalar(
        select(NoticeRead).where(
            NoticeRead.notice_id == notice.id, NoticeRead.user_id == user.id
        )
    )
    return NoticeOut(
        id=notice.id,
        title=notice.title,
        body=notice.body,
        level=notice.level,
        is_popup=notice.is_popup,
        published_at=notice.published_at,
        expires_at=notice.expires_at,
        author_name=author.display_name if author else None,
        read=read is not None,
        created_at=notice.created_at,
        from_release=notice.seed_key is not None,
    )


def _publish(notice: Notice) -> None:
    """발행한다 — 배포 안내(`seed_key`)는 그 판의 날짜(`created_at`, 씨앗의 날짜)로, 손으로 쓴
    초안은 지금으로. 버전 안내를 발행한 날로 세우면 「언제 이 판이 나왔나」 를 잃는다."""
    if notice.published_at is None:
        notice.published_at = notice.created_at if notice.seed_key else datetime.now(UTC)


@router.get("", response_model=list[NoticeOut])
def list_notices(
    include_drafts: bool = Query(default=False),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[NoticeOut]:
    stmt = select(Notice)
    if not include_drafts or not user.is_system_admin:
        # 초안은 쓴 사람만 본다. 반쯤 쓴 글이 전사에 보이면 그 자체가 사고다.
        stmt = stmt.where(Notice.published_at.is_not(None))
    # 게시 시각이 먼저(초안은 만든 시각) — 배포 안내는 판의 날짜에 선다.
    rows = db.scalars(
        stmt.order_by(
            func.coalesce(Notice.published_at, Notice.created_at).desc(),
            Notice.created_at.desc(),
        ).limit(200)
    )
    return [_out(db, row, user) for row in rows]


@router.get("/popup", response_model=list[NoticeOut])
def popup_notices(
    user: User = Depends(current_user), db: Session = Depends(get_db)
) -> list[NoticeOut]:
    """읽지 않은 팝업 공지. **스스로 뜬다** — 공지 화면에 들어가야만 보이면
    배포 없이 안내를 전한다는 목적이 성립하지 않는다."""
    now = datetime.now(UTC)
    read_ids = select(NoticeRead.notice_id).where(NoticeRead.user_id == user.id)
    rows = db.scalars(
        select(Notice)
        .where(
            Notice.is_popup.is_(True),
            Notice.published_at.is_not(None),
            Notice.id.not_in(read_ids),
            (Notice.expires_at.is_(None)) | (Notice.expires_at > now),
        )
        .order_by(Notice.created_at.desc())
    )
    return [_out(db, row, user) for row in rows]


@router.post("", response_model=NoticeOut, status_code=201)
def create_notice(
    payload: NoticeWriteRequest,
    admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> NoticeOut:
    notice = Notice(
        title=payload.title,
        body=payload.body,
        level=payload.level,
        is_popup=payload.is_popup,
        published_at=datetime.now(UTC) if payload.publish else None,
        expires_at=payload.expires_at,
        author_id=admin.id,
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return _out(db, notice, admin)


@router.post("/publish-drafts", response_model=NoticePublishedOut)
def publish_drafts(
    _: User = Depends(require_system_admin), db: Session = Depends(get_db)
) -> NoticePublishedOut:
    """**배포 안내 초안** 모두 발행 — 배포가 넣은 업데이트 안내(`seed_key`)만 한 번에. 손으로
    쓰다 둔 초안(다음 주 점검 안내처럼 일부러 둔 글)은 하나씩 「발행」 한다 — 함께 나가면
    되돌리기 어렵다. 발행 시각은 `_publish` 의 규칙(그 판의 날짜)."""
    drafts = list(
        db.scalars(
            select(Notice).where(Notice.published_at.is_(None), Notice.seed_key.is_not(None))
        )
    )
    for one in drafts:
        _publish(one)
    db.commit()
    return NoticePublishedOut(published=len(drafts))


@router.post("/{notice_id}/publish", response_model=NoticeOut)
def publish_notice(
    notice_id: uuid.UUID,
    admin: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> NoticeOut:
    """초안 하나를 발행한다(이미 발행했으면 그대로)."""
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise NotFound(code("NOTICES", 1), "공지를 찾을 수 없습니다.")
    _publish(notice)
    db.commit()
    db.refresh(notice)
    return _out(db, notice, admin)


@router.post("/{notice_id}/read", response_model=NoticeOut)
def mark_read(
    notice_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> NoticeOut:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise NotFound(code("NOTICES", 1), "공지를 찾을 수 없습니다.")
    existing = db.scalar(
        select(NoticeRead).where(
            NoticeRead.notice_id == notice.id, NoticeRead.user_id == user.id
        )
    )
    if existing is None:
        db.add(NoticeRead(notice_id=notice.id, user_id=user.id))
        db.commit()
    return _out(db, notice, user)


@router.delete("/{notice_id}", status_code=204)
def delete_notice(
    notice_id: uuid.UUID,
    _: User = Depends(require_system_admin),
    db: Session = Depends(get_db),
) -> None:
    notice = db.get(Notice, notice_id)
    if notice is None:
        raise NotFound(code("NOTICES", 1), "공지를 찾을 수 없습니다.")
    db.delete(notice)
    db.commit()
