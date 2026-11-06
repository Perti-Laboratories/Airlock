"""Durable return-record permission and replay cursor."""
from alembic import op
import sqlalchemy as sa
revision = '0010'
down_revision = '0009'
branch_labels = depends_on = None

def upgrade():
    op.create_table('record_exchange',
        sa.Column('domain_id', sa.Uuid(), sa.ForeignKey('domains.id'), primary_key=True),
        sa.Column('policy', sa.JSON()),
        sa.Column('policy_revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inbound_revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('inbound_hash', sa.String(64)), sa.Column('inbound', sa.JSON()),
        sa.Column('error', sa.String(240)))

def downgrade():
    op.execute(sa.text('UPDATE release_policies SET paused = true, revision = revision + 1'))
    op.drop_table('record_exchange')
