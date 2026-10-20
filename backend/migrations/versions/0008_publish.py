"""해석 작업은 건 사람의 것 — 게시해야 남이 본다.

전에는 부서 단위로 열려 있어(전역 + 열린 부서 + 내 부서) 실패한 작업 · 메시만 바꿔 본 작업까지
모두에게 보였다. 이제 작업은 건 사람과 시스템 관리자만 보고, 게시한 것(`published_at`)은 누구나
본다(2026-10-20).

**이미 끝난 작업은 게시된 것으로 옮긴다** — 규칙이 바뀌는 순간 남이 보던 결과가 사라지면 그 결과를
가리키던 보고서 · 링크가 끊긴다. 끝나지 않은 작업(실패 · 취소 · 대기 · 도는 중)은 건 사람의 것으로
남는다. 행을 새로 넣는 것이 아니라 있는 행의 뜻을 옮기는 것이라 여기서 한다.

Revision ID: 0008_publish
Revises: 0007_ontology
Create Date: 2026-10-20 10:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008_publish"
down_revision: Union[str, Sequence[str], None] = "0007_ontology"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "simulations", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("simulations", sa.Column("published_by_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_simulations_published_at"), "simulations", ["published_at"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_simulations_published_by_id_users"),
        "simulations",
        "users",
        ["published_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        "UPDATE simulations SET published_at = COALESCE(finished_at, created_at), "
        "published_by_id = requested_by_id "
        "WHERE status = 'done' AND deleted_at IS NULL"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        op.f("fk_simulations_published_by_id_users"), "simulations", type_="foreignkey"
    )
    op.drop_index(op.f("ix_simulations_published_at"), table_name="simulations")
    op.drop_column("simulations", "published_by_id")
    op.drop_column("simulations", "published_at")
