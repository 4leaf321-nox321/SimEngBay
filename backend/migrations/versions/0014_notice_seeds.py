"""배포에 실려 오는 업데이트 안내 — `notices.seed_key` 와 `notice_seed_keys` 표.

판마다 `seeds/notices/<날짜>-v<판>.md` 가 배포마다 공지 **초안**으로 들어온다
(`scripts/import_notices.py`, CompCore · MatNexus 와 같은 길). 같은 키는 두 번 안 들어오고, 지운
초안도 되살아나지 않게 넣은 키를 따로 기억한다.

Revision ID: 0014_notice_seeds
Revises: 0013_runtime_settings
Create Date: 2026-11-28 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014_notice_seeds"
down_revision: Union[str, Sequence[str], None] = "0013_runtime_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("notices", sa.Column("seed_key", sa.String(length=100), nullable=True))
    op.create_unique_constraint("uq_notices_seed_key", "notices", ["seed_key"])
    op.create_table(
        "notice_seed_keys",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("notice_seed_keys")
    op.drop_constraint("uq_notices_seed_key", "notices", type_="unique")
    op.drop_column("notices", "seed_key")
