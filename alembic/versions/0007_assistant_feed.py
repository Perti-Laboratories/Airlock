"""Persistent local assistant-feed acknowledgement receipts."""
from alembic import op
import sqlalchemy as sa
revision = '0007'
down_revision = '0006'
branch_labels = depends_on = None


def upgrade():
    op.create_table('feed_acknowledgements',
        sa.Column('key', sa.String(80), primary_key=True),
        sa.Column('domain_id', sa.Uuid(), sa.ForeignKey('domains.id'), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_messages_feed_order', 'messages', ['created_at', 'id'])


def downgrade():
    op.drop_index('ix_messages_feed_order', table_name='messages')
    op.drop_table('feed_acknowledgements')
