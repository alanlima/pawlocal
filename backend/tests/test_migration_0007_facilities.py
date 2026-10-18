import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text


@pytest.mark.integration
def test_0007_backfills_facilities_in_order_and_handles_empty_arrays():
    database_url = os.getenv("PAWLOCAL_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set PAWLOCAL_TEST_DATABASE_URL for migration integration checks")

    engine = create_engine(database_url, pool_pre_ping=True)
    schema = f"pawlocal_migration_{uuid4().hex}"
    ordered_place_id, empty_place_id = uuid4(), uuid4()
    try:
        with engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))

        with engine.connect() as connection:
            connection.execute(text(f'SET search_path TO "{schema}"'))
            config = Config("alembic.ini")
            config.attributes["connection"] = connection
            command.upgrade(config, "0006_contribution_validation")

            connection.execute(
                text(
                    "INSERT INTO places (id, name, category, area, facilities) "
                    "VALUES "
                    "(:ordered_id, 'Ordered facilities fixture', 'dog_park', "
                    "'Brisbane City', ARRAY['Shade', 'Fenced', 'Drinking water', "
                    "'Fenced']::varchar(80)[]), "
                    "(:empty_id, 'Empty facilities fixture', 'dog_park', "
                    "'Brisbane City', ARRAY[]::varchar(80)[])"
                ),
                {"ordered_id": ordered_place_id, "empty_id": empty_place_id},
            )
            connection.commit()

            command.upgrade(config, "head")

            assert connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one() == "0007_normalize_place_facilities"
            ordered_facilities = connection.execute(
                text(
                    "SELECT facility FROM place_facilities "
                    "WHERE place_id = :place_id ORDER BY ordinal"
                ),
                {"place_id": ordered_place_id},
            ).scalars().all()
            assert ordered_facilities == ["Shade", "Fenced", "Drinking water"]
            assert connection.execute(
                text(
                    "SELECT ordinal FROM place_facilities "
                    "WHERE place_id = :place_id ORDER BY ordinal"
                ),
                {"place_id": ordered_place_id},
            ).scalars().all() == [0, 1, 2]
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM place_facilities "
                    "WHERE place_id = :place_id"
                ),
                {"place_id": empty_place_id},
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    "SELECT COUNT(*) FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = 'places' "
                    "AND column_name = 'facilities'"
                ),
                {"schema": schema},
            ).scalar_one() == 0
            connection.commit()
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        engine.dispose()
