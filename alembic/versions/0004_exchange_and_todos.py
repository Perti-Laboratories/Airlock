"""Standalone connector state, opaque identities and local Todo records."""
from alembic import op
import sqlalchemy as sa

revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('todos',
        sa.Column('id',sa.Uuid(),primary_key=True),
        sa.Column('domain_id',sa.Uuid(),sa.ForeignKey('domains.id'),nullable=False),
        sa.Column('title',sa.String(240),nullable=False),
        sa.Column('description',sa.Text(),nullable=False),
        sa.Column('todo_type',sa.String(80),nullable=False),
        sa.Column('owner_type',sa.String(80),nullable=False),
        sa.Column('owner_ref',sa.String(240)),
        sa.Column('due_at',sa.DateTime(timezone=True)),
        sa.Column('estimated_minutes',sa.Integer()),
        sa.Column('scheduled_start_at',sa.DateTime(timezone=True)),
        sa.Column('priority',sa.String(40),nullable=False),
        sa.Column('status',sa.String(40),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('deleted',sa.Boolean(),nullable=False),
        sa.Column('source_refs',sa.JSON(),nullable=False),
        sa.Column('provenance',sa.JSON(),nullable=False),
        sa.Column('release_title',sa.String(160)),
        sa.Column('release_due',sa.Boolean(),nullable=False),
        sa.Column('release_revision',sa.Integer()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('exchange_state',
        sa.Column('domain_id',sa.Uuid(),sa.ForeignKey('domains.id'),primary_key=True),
        sa.Column('pairing_id',sa.Uuid(),nullable=False),
        sa.Column('endpoint',sa.String(500),nullable=False),
        sa.Column('public_key',sa.String(44),nullable=False),
        sa.Column('enabled',sa.Boolean(),nullable=False),
        sa.Column('allow_availability',sa.Boolean(),nullable=False),
        sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('acknowledged_revision',sa.Integer(),nullable=False),
        sa.Column('fingerprint',sa.String(64)),
        sa.Column('outbox',sa.JSON()),
        sa.Column('last_sent_at',sa.DateTime(timezone=True)),
        sa.Column('next_attempt_at',sa.DateTime(timezone=True)),
        sa.Column('failures',sa.Integer(),nullable=False),
        sa.Column('error',sa.String(240)),
        sa.Column('inbound_revision',sa.Integer(),nullable=False),
        sa.Column('inbound_hash',sa.String(64)),
        sa.Column('inbound',sa.JSON()),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('updated_at',sa.DateTime(timezone=True),nullable=False))
    op.create_table('export_identities',
        sa.Column('local_key',sa.String(320),primary_key=True),
        sa.Column('domain_id',sa.Uuid(),sa.ForeignKey('domains.id'),nullable=False),
        sa.Column('export_id',sa.Uuid(),nullable=False,unique=True))


def downgrade():
    op.drop_table('export_identities')
    op.drop_table('exchange_state')
    op.drop_table('todos')
