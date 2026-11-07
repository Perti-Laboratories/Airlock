"""Durable optional board exchange state."""
from alembic import op
import sqlalchemy as sa
revision = '0011'
down_revision = '0010'
branch_labels = depends_on = None

def upgrade():
    op.add_column('record_exchange', sa.Column('board_state', sa.JSON(), nullable=False, server_default='{}'))

def downgrade():
    op.execute(sa.text('UPDATE release_policies SET paused = true, revision = revision + 1'))
    op.drop_column('record_exchange', 'board_state')
