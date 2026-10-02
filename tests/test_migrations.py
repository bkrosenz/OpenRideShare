from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


def test_initial_migration_creates_persistent_schema(tmp_path):
    database_path = tmp_path / "migration.db"
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path}")
    command.upgrade(config, "head")
    inspector = inspect(create_engine(f"sqlite:///{database_path}"))
    assert set(inspector.get_table_names()) == {"alembic_version", "users", "drivers", "invitations", "rides"}