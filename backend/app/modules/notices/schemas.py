"""공지 API 형태."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoticeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    body: str
    level: str
    is_popup: bool
    published_at: datetime | None
    expires_at: datetime | None
    author_name: str | None
    read: bool
    """내가 읽었나. **서버가 든다** — 브라우저에만 두면 다른 PC 에서 또 뜬다."""
    created_at: datetime
    from_release: bool = False
    """배포에 실려 온 업데이트 안내인가(`seed_key` 가 있다) — 화면은 쓴 사람 자리에
    「배포 안내」 를 보인다."""


class NoticePublishedOut(BaseModel):
    """「배포 안내 초안 모두 발행」 의 결과 — 발행한 수."""

    published: int


class NoticeWriteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    level: str = Field(default="info", pattern="^(info|warning|urgent)$")
    is_popup: bool = False
    publish: bool = True
    """false 면 초안으로 둔다. 급한 공지를 반쯤 쓰다 저장하는 일이 실제로 있다."""
    expires_at: datetime | None = None
