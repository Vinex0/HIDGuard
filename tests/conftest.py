import pytest

from hidguard.features.features import Features
from hidguard.storage.sqlite_repo import SqliteRepo


@pytest.fixture
def repo():
    """An empty database per test, in memory so nothing touches data/hidguard.db."""
    r = SqliteRepo(":memory:")
    yield r
    r.close()


@pytest.fixture
def features(repo):
    """Feature extraction bound to the same repo the test sees.

    Requesting `repo` here rather than building a second one matters: pytest
    caches a fixture per test, so events a test writes through `repo` are the
    ones this reads back.
    """
    return Features(repo)