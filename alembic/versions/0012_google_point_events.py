"""Preserve nonblocking, zero-duration Google events without inventing an end time."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = depends_on = None


def upgrade():
    op.drop_constraint('event_time_order', 'calendar_events', type_='check')
    op.create_check_constraint('event_time_order', 'calendar_events',
        "end_at > start_at OR (end_at = start_at AND source_id IS NOT NULL "
        "AND external_provider IS NOT DISTINCT FROM 'google_calendar' "
        "AND external_event_id IS NOT NULL AND NOT all_day AND NOT blocks_time "
        "AND recurrence_rule IS NULL)")


def downgrade():
    # Do not silently delete or alter provider timestamps to fit the old schema.
    if op.get_bind().scalar(sa.text(
            'SELECT EXISTS (SELECT 1 FROM calendar_events WHERE end_at = start_at)')):
        raise RuntimeError('Cannot downgrade while imported point events are stored; retain revision 0012.')
    op.drop_constraint('event_time_order', 'calendar_events', type_='check')
    op.create_check_constraint('event_time_order', 'calendar_events', 'end_at > start_at')
