"""The failure paths a user can actually reach, and what they see instead of a traceback."""

import argparse
import sqlite3

import pytest

from hidguard import dashboard, simulate
from hidguard.errors import StorageError
from hidguard.models.device_model import Device
from hidguard.storage.sqlite_repo import SqliteRepo


def test_unopenable_database_raises_storage_error(tmp_path):
    """A path that cannot be a database is reported, not a sqlite3 traceback."""
    missing_directory = tmp_path / "no-such-dir" / "hidguard.db"

    with pytest.raises(StorageError) as excinfo:
        SqliteRepo(missing_directory)

    assert str(missing_directory) in str(excinfo.value)


def test_write_after_close_raises_storage_error(repo):
    """Writes to a connection that has gone away surface as StorageError.

    Stands in for the case the README warns about -- a database owned by
    another user after mixing sudo and non-sudo runs -- which is the same
    sqlite3.Error arriving in the same place, inside a background thread.
    """
    repo.close()

    with pytest.raises(StorageError):
        repo.save_device(Device(id="dev-1"))


def test_reads_after_close_raise_storage_error(repo):
    """The dashboard's read path fails the same way its write path does."""
    repo.close()

    with pytest.raises(StorageError):
        repo.list_detections()


def test_close_is_safe_to_call_twice(repo):
    """Shutdown runs from a finally block and must not fail there."""
    repo.close()
    repo.close()


def test_negative_limit_is_rejected(repo):
    """SQLite reads a negative LIMIT as 'no limit', so the repo refuses it."""
    with pytest.raises(ValueError):
        repo.list_session(limit=-1)


@pytest.mark.parametrize("bad_value", ["0", "-3", "abc", "1.5", ""])
def test_limit_flag_rejects_bad_values(bad_value):
    with pytest.raises(argparse.ArgumentTypeError):
        dashboard._positive_int(bad_value)


@pytest.mark.parametrize("bad_value", ["0", "-1", "nope", ""])
def test_interval_flag_rejects_bad_values(bad_value):
    with pytest.raises(argparse.ArgumentTypeError):
        dashboard._positive_float(bad_value)


@pytest.mark.parametrize("bad_value", ["-1", "soon", "2.5"])
def test_countdown_flag_rejects_bad_values(bad_value):
    with pytest.raises(argparse.ArgumentTypeError):
        simulate._countdown_seconds(bad_value)


def test_bad_flag_value_exits_with_usage(capsys):
    """argparse reports the flag itself; the program never starts on bad input."""
    parser = argparse.ArgumentParser(prog="hidguard")
    dashboard.add_arguments(parser)

    with pytest.raises(SystemExit) as excinfo:
        parser.parse_args(["--interval", "-1"])

    assert excinfo.value.code == 2  # argparse's usage-error code, not a crash
    assert "greater than 0" in capsys.readouterr().err


def test_storage_error_keeps_the_original_cause(tmp_path):
    """The sqlite3 error stays attached, so a real bug is still diagnosable."""
    with pytest.raises(StorageError) as excinfo:
        SqliteRepo(tmp_path / "no-such-dir" / "hidguard.db")

    assert isinstance(excinfo.value.__cause__, sqlite3.Error)
