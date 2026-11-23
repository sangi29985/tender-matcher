from alembic import context
from sqlalchemy import create_engine, pool, text

from app.database import Base, database_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = _url()
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        if connection.dialect.name == "postgresql":
            # The web app and the worker both migrate on start; let only one run at a time.
            connection.execute(text("SELECT pg_advisory_lock(727274)"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite can't ALTER most columns in place; batch mode rebuilds the table instead.
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
