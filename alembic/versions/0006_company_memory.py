"""Optional company-memory prototype state; no credentials in the database."""
from alembic import op
import sqlalchemy as sa
revision = '0006'
down_revision = '0005'
branch_labels = depends_on = None


def upgrade():
    def domain(): return sa.Column('domain_id', sa.Uuid(), sa.ForeignKey('domains.id'), nullable=False)
    def times(): return [sa.Column('created_at', sa.DateTime(timezone=True), nullable=False), sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False)]
    op.create_table('company_connection', sa.Column('domain_id', sa.Uuid(), sa.ForeignKey('domains.id'), primary_key=True),
        sa.Column('company_id', sa.String(80), nullable=False), sa.Column('name', sa.String(160), nullable=False),
        sa.Column('endpoint', sa.String(240), nullable=False), sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('extraction_enabled', sa.Boolean(), nullable=False), sa.Column('next_run_at', sa.DateTime(timezone=True)),
        sa.Column('last_run_at', sa.DateTime(timezone=True)), sa.Column('error', sa.String(240)),
        sa.Column('embedding_spec', sa.JSON(), nullable=False), *times())
    op.create_table('company_sources', domain(),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('knowledge_sources.id'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False), sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('cursor', sa.Integer(), nullable=False), sa.Column('status', sa.String(40), nullable=False), sa.Column('error', sa.String(240)))
    op.create_table('company_candidates', domain(), sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('source_id', sa.Uuid(), sa.ForeignKey('knowledge_sources.id'), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('title', sa.String(240), nullable=False), sa.Column('content', sa.Text(), nullable=False),
        sa.Column('evidence', sa.Text(), nullable=False), sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=False), sa.Column('embedding_spec', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(40), nullable=False), sa.Column('receipt', sa.JSON()), *times(),
        sa.UniqueConstraint('source_id', 'content_hash', 'fingerprint'))
    op.add_column('knowledge_sources', sa.Column('company_restricted', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column('knowledge_sources', 'company_restricted')
    for name in ['company_candidates', 'company_sources', 'company_connection']: op.drop_table(name)
