from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    pool_timeout=3,
    connect_args={"connect_timeout": 3},
)


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as session:
        yield session


def check_database() -> bool:
    with engine.connect() as connection:
        with connection.begin():
            connection.execute(text("SET LOCAL statement_timeout = 3000"))
            result = connection.execute(text("SELECT 1"))

            return result.scalar_one() == 1
