"""Default-off plugged-in keep-awake preference."""
from alembic import op
import sqlalchemy as sa
revision = '0014'
down_revision = '0013'
branch_labels = depends_on = None


def upgrade():
    op.add_column('local_state', sa.Column('keep_syncing_plugged_in', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade():
    op.drop_column('local_state', 'keep_syncing_plugged_in')
