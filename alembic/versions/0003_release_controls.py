"""Add local release rules and event review exceptions; no transport is enabled."""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "release_policies",
        sa.Column(
            "domain_id", sa.Uuid(), sa.ForeignKey("domains.id"), primary_key=True
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "release_overrides",
        sa.Column(
            "event_id", sa.Uuid(), sa.ForeignKey("calendar_events.id"), primary_key=True
        ),
        sa.Column("domain_id", sa.Uuid(), sa.ForeignKey("domains.id"), nullable=False),
        sa.Column("event_revision", sa.Integer(), nullable=False),
        sa.Column("policy_revision", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(40), nullable=False),
        sa.Column("display_title", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    op.drop_table("release_overrides")
    op.drop_table("release_policies")
