from sqlalchemy import URL

from app.core.config import Settings
from app.db.session import build_database_url


def test_build_database_url_uses_async_postgres_driver() -> None:
    settings = Settings(
        _env_file=None,
        postgres_host="database.internal",
        postgres_port=5432,
        postgres_db="agenthire_test",
        postgres_user="agenthire_test_user",
        postgres_password="test@password:123",
    )

    database_url = build_database_url(settings)

    assert isinstance(database_url, URL)
    assert database_url.drivername == "postgresql+asyncpg"
    assert database_url.host == "database.internal"
    assert database_url.port == 5432
    assert database_url.database == "agenthire_test"
    assert database_url.username == "agenthire_test_user"
    assert database_url.password == "test@password:123"
