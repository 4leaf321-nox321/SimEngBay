"""서버에서 고치는 설정 — `runtime_settings` 표(2026-11-25).

`config.py` 머리글의 3단(서버 설정 → 환경 · `.env` → 기본값) 중 첫 단이다. 무엇을 여기 둘 수
있는지 · 언제 듣는지는 `runtime.py` 의 표(`KNOBS`)가 정한다 — 이 표는 값만 든다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RuntimeSetting(Base):
    """한 열쇠의 서버 설정 값. **행이 없으면 환경 · `.env` · 기본값으로 물러선다.**"""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
