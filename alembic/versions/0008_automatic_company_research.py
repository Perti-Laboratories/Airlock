"""Optional automatic company research."""
from alembic import op
import sqlalchemy as sa
revision = '0008'
down_revision = '0007'
branch_labels = depends_on = None

def upgrade():
    op.add_column('company_connection', sa.Column('automatic_research',sa.Boolean(),nullable=False,server_default=sa.true()))

def downgrade():
    op.drop_column('company_connection','automatic_research')
