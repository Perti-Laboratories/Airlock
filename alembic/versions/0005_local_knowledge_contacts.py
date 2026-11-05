"""Local source retrieval, contacts and persistent model preference."""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def identity():
    return [sa.Column('id', sa.Uuid(), primary_key=True),
            sa.Column('domain_id', sa.Uuid(), sa.ForeignKey('domains.id'), nullable=False)]


def timestamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.add_column('local_state', sa.Column('chat_model', sa.String(160)))
    op.create_table('knowledge_sources', *identity(),
        sa.Column('source_key', sa.String(320), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('title', sa.String(240), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('source_refs', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('error', sa.String(240)), *timestamps(),
        sa.UniqueConstraint('domain_id', 'source_key'))
    op.create_table('knowledge_chunks', *identity(),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('knowledge_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('model', sa.String(160), nullable=False),
        sa.Column('dimensions', sa.Integer(), nullable=False),
        sa.Column('embedding', Vector(), nullable=False),
        sa.UniqueConstraint('source_id', 'ordinal'))
    op.create_index('ix_knowledge_chunks_source_id', 'knowledge_chunks', ['source_id'])
    op.create_table('contacts', *identity(),
        sa.Column('name', sa.String(240), nullable=False),
        sa.Column('normalized_name', sa.String(260), nullable=False),
        sa.Column('email', sa.String(320), nullable=False),
        sa.Column('phone', sa.String(80), nullable=False),
        sa.Column('organization', sa.String(240), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('last_contact_at', sa.DateTime(timezone=True)),
        sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('source_refs', sa.JSON(), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False), *timestamps())
    op.create_table('contact_interactions', *identity(),
        sa.Column('contact_id', sa.Uuid(), sa.ForeignKey('contacts.id', ondelete='CASCADE'), nullable=False),
        sa.Column('interaction_type', sa.String(80), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        sa.Column('source_refs', sa.JSON(), nullable=False),
        sa.Column('provenance', sa.JSON(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False), *timestamps())
    op.create_index('ix_contact_interactions_contact_id', 'contact_interactions', ['contact_id'])


def downgrade():
    for table in ('contact_interactions', 'contacts', 'knowledge_chunks', 'knowledge_sources'):
        op.drop_table(table)
    op.drop_column('local_state', 'chat_model')
