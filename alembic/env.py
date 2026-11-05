from alembic import context
from sqlalchemy import create_engine
from airlock.config import Settings
from airlock.models import Base
engine = create_engine(Settings().database_url, hide_parameters=True)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
