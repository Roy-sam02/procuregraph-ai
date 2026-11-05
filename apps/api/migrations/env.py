import os

from alembic import context
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import URL


def run_migrations() -> None:
    url = URL.create(
        "postgresql+psycopg",
        username="postgres",
        password=os.environ["PROCUREGRAPH_DB_PASSWORD"],
        host="127.0.0.1",
        port=int(os.environ["PROCUREGRAPH_DB_PORT"]),
        database="procuregraph",
    )
    engine = create_engine(url, poolclass=pool.NullPool)
    try:
        with engine.connect() as connection:
            context.configure(connection=connection)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


run_migrations()
