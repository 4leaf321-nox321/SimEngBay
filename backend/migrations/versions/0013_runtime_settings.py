"""서버에서 고치는 설정 — `runtime_settings` 표와 작업의 `run_settings`(만들 때 고정한 값).

`.env` 에 적은 단계 설정은 앱을 다시 띄워야 들었다. 해석을 조정하는 값(본딩 방식 · 선형 솔버 ·
허용오차 · 스레드 · STE 메모리 상한 · STE 연결)은 서버 화면에서 고치고, 결과를 바꾸는 값은 작업을
만들 때 그 작업에 적어 둔다(`app/modules/server/runtime.py`).

Revision ID: 0013_runtime_settings
Revises: 0012_study_frequency
Create Date: 2026-11-25 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0013_runtime_settings"
down_revision: Union[str, Sequence[str], None] = "0012_study_frequency"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_by_id", sa.UUID(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_id"],
            ["users.id"],
            name=op.f("fk_runtime_settings_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_runtime_settings")),
    )
    op.add_column(
        "simulations",
        sa.Column(
            "run_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    # 지우면 서버 화면에서 고친 값이 사라지고 `.env` 값으로 돌아간다 — 작업 · 결과는 그대로다.
    op.drop_column("simulations", "run_settings")
    op.drop_table("runtime_settings")
