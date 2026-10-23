"""해석 작업의 폴더(`simulations.folder`) — 해석 작업 · DOE 목록을 폴더로 나눠 본다(ADR 0013).

폴더는 표가 따로 없다 — 항목이 들고 있는 경로(`고객A/2026`)에서 나무를 세운다(CompCore 와 같은
규칙). 맨 위는 빈 문자열이라 있던 작업은 모두 맨 위(폴더 없음)에 선다.

Revision ID: 0011_simulation_folder
Revises: 0010_pat_delegated_client
Create Date: 2026-10-23 21:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0011_simulation_folder"
down_revision: Union[str, Sequence[str], None] = "0010_pat_delegated_client"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 기본값이 있는 NOT NULL 칸 — PostgreSQL 11 부터 표를 다시 쓰지 않는다.
    op.add_column(
        "simulations",
        sa.Column("folder", sa.String(length=255), nullable=False, server_default=""),
    )
    op.create_index("ix_simulations_folder", "simulations", ["folder"])


def downgrade() -> None:
    # 지우면 사람이 나눠 둔 폴더가 사라진다 — 작업은 그대로 남는다(모두 맨 위로).
    op.drop_index("ix_simulations_folder", table_name="simulations")
    op.drop_column("simulations", "folder")
