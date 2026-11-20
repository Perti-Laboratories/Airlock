"""Durable local extraction progress and opt-out."""
from alembic import op
import sqlalchemy as sa
revision = '0015'
down_revision = '0014'
branch_labels = depends_on = None


def upgrade():
    op.add_column('local_state', sa.Column('automatic_context', sa.Boolean(), nullable=False, server_default=sa.true()))
    for column in [sa.Column('extraction_hash', sa.String(64)),
                   sa.Column('extraction_cursor', sa.Integer(), nullable=False, server_default='0'),
                   sa.Column('extraction_status', sa.String(40), nullable=False, server_default='pending'),
                   sa.Column('extraction_error', sa.String(240)),
                   sa.Column('extraction_retry_at', sa.DateTime(timezone=True))]:
        op.add_column('knowledge_sources', column)


def downgrade():
    for name in ('extraction_hash','extraction_cursor','extraction_status','extraction_error','extraction_retry_at'):
        op.drop_column('knowledge_sources', name)
    op.drop_column('local_state','automatic_context')
