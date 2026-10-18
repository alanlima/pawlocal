from alembic import context
from sqlalchemy import create_engine, pool

from pawlocal.config import settings
from pawlocal.infrastructure import models  # noqa: F401
from pawlocal.infrastructure.database import Base

config = context.config
config.set_main_option(
    "sqlalchemy.url", settings.sqlalchemy_url.render_as_string(hide_password=False).replace("%", "%%")
)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.sqlalchemy_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(settings.sqlalchemy_url, poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
