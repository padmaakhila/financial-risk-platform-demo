from alembic import context

from backend.database.session import get_engine
from backend.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = get_engine()
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")  # SQLite needs batch ALTER
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
