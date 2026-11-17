"""Local nonblocking context windows."""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = depends_on = None


def upgrade():
    op.add_column('calendar_events', sa.Column('context_type', sa.String(80), nullable=True))
    op.create_check_constraint('context_is_nonblocking', 'calendar_events',
        "item_kind <> 'context_window' OR (NOT blocks_time AND scheduling_effect IN "
        "('informational', 'prefer', 'prefer_avoid', 'strongly_avoid') "
        "AND context_type IS NOT NULL AND context_type IN "
        "('availability', 'childcare', 'energy', 'household', 'location', 'routine'))")


def downgrade():
    if op.get_bind().scalar(sa.text(
            "SELECT EXISTS (SELECT 1 FROM calendar_events WHERE item_kind = 'context_window')")):
        raise RuntimeError('Cannot downgrade while context windows are stored; retain revision 0013.')
    op.drop_constraint('context_is_nonblocking', 'calendar_events', type_='check')
    op.drop_column('calendar_events', 'context_type')
