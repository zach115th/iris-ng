from alembic import context
from logging.config import fileConfig
from sqlalchemy import engine_from_config
from sqlalchemy import pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
fileConfig(config.config_file_name)

import os
os.environ["ALEMBIC"] = "1"

from app.configuration import SQLALCHEMY_BASE_ADMIN_URI, PG_DB_

config.set_main_option('sqlalchemy.url', SQLALCHEMY_BASE_ADMIN_URI + PG_DB_)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline():
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )

        # iris-next: re-enable the transaction wrapper so migrations actually
        # commit. Upstream IRIS commented this out with the cryptic note
        # "Fixes stuck transaction. Need more info on that" — the side effect
        # was that no migration since has been persisted to the alembic_version
        # table or to the schema. Tables got created via db.create_all()
        # instead, but column-adds on existing tables silently dropped on the
        # floor (observed when adding ai_backend_* columns to server_settings —
        # the migration logged "Running upgrade" but no commit happened, so
        # the next ServerSettings.query.first() failed with UndefinedColumn).
        # Wrapping in begin_transaction() restores normal Alembic commit
        # semantics for new migrations.
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
