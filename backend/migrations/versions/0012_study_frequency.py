"""스터디의 주파수 요구 조건 — 목표 주파수 · 회피 대역을 스터디에 한 벌 저장한다.

판정은 저장하지 않는다 — 읽을 때 셈한다(`app/modules/simulations/frequency.py`).

Revision ID: 0012_study_frequency
Revises: 0011_simulation_folder
Create Date: 2026-11-16 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012_study_frequency"
down_revision: Union[str, Sequence[str], None] = "0011_simulation_folder"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "study_frequency_requirements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("study_id", sa.String(length=120), nullable=False),
        sa.Column("rows", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
            name=op.f("fk_study_frequency_requirements_updated_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_study_frequency_requirements")),
    )
    op.create_index(
        op.f("ix_study_frequency_requirements_study_id"),
        "study_frequency_requirements",
        ["study_id"],
        unique=True,
    )


def downgrade() -> None:
    # 지우면 사람이 저장한 요구 조건이 사라진다 — 작업 · 결과는 그대로 남는다.
    op.drop_index(
        op.f("ix_study_frequency_requirements_study_id"),
        table_name="study_frequency_requirements",
    )
    op.drop_table("study_frequency_requirements")
