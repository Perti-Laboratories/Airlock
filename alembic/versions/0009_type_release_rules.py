"""Outbound disclosure ceilings by record type; preserve existing approvals."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = depends_on = None


def upgrade():
    op.add_column('release_policies', sa.Column('type_rules', sa.JSON(), nullable=False,
        server_default='{"calendar":"private","todo":"private","contacts":"private","memory":"private","company_memory":"private"}'))
    # Preserve the old source-level and per-task review behavior, including pauses.
    # Neither source rules nor individual approvals are changed by this migration.
    op.execute(sa.text("""UPDATE release_policies SET type_rules =
        '{"calendar":"original","todo":"title_due","contacts":"private","memory":"private","company_memory":"private"}'"""))


def downgrade():
    # Removing ceilings could broaden outbound disclosure; require deliberate resume.
    op.execute(sa.text('UPDATE release_policies SET paused = true, revision = revision + 1'))
    op.drop_column('release_policies', 'type_rules')
