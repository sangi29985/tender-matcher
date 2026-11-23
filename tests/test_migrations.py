from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.database import MIGRATIONS_DIR, Base


def test_migrations_build_the_current_schema(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")

    engine = create_engine(url)
    with engine.connect() as connection:
        differences = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    engine.dispose()
    assert differences == [], (
        "Models changed without a migration: run alembic revision --autogenerate"
    )

    command.downgrade(config, "base")
