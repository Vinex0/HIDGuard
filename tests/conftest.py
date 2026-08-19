import pytest

from hidguard.storage.sqlite_repo import SqliteRepo


@pytest.fixture
def repo():
    """An empty database per test, in memory so nothing touches data/hidguard.db."""
    r = SqliteRepo(":memory:")
    yield r
    r.close()