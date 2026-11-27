import os
import pytest

if os.environ.get("DB_NAME") != "infrapulse_test":
    raise RuntimeError(
        "Tests must run against infrapulse_test database"
    )

from app.config import settings
from app.database import engine
from sqlalchemy import text


if settings.db_name != "infrapulse_test":
    raise RuntimeError(
        "Unsafe database configuration"
    )


@pytest.fixture(autouse=True)
def clean_database():
    with engine.begin() as connection:
        database_name = connection.execute(
            text("SELECT current_database()")
        ).scalar_one()

        if database_name != "infrapulse_test":
            raise RuntimeError("Unsafe database connection")

        connection.execute(text(
            "TRUNCATE TABLE scan_results, health_checks, "
            "scans, devices RESTART IDENTITY"
        ))

    yield