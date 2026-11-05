from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def database(settings):
    engine = create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    return engine, sessionmaker(engine, expire_on_commit=False)
