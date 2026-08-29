import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from uuid import UUID

from hidguard.errors import StorageError
from hidguard.models.detection import Detection
from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session
from hidguard.storage.schema import SCHEMA


class SqliteRepo:
    """Reads and writes every model to one SQLite file.

    Opened with check_same_thread=False because the udev listener, each reader
    thread, and the scorer all share one connection; writes are serialised by
    _write_lock, and WAL mode keeps a separate dashboard process reading while
    they happen.
    """

    def __init__(self, db_path: str | Path):
        """Connects to db_path, creating the file and the schema if needed.

        Raises:
            StorageError: the file cannot be opened or the schema not created --
                a missing directory, or a database owned by another user (the
                usual cause: mixing sudo and non-sudo runs).
        """
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as error:
            raise StorageError(
                f"Could not open the database at {db_path}: {error}. "
                "If it exists but belongs to another user, run every hidguard "
                "command the same way (see 'Why sudo' in the README) or delete "
                "data/hidguard.db* and start fresh."
            ) from error
        self._write_lock = threading.Lock()

    def _write(self, statement: str, data: dict[str, object]) -> None:
        """Runs one write statement under the lock, as a StorageError on failure.

        Every writer runs in a background thread, where a bare sqlite3 error
        would kill that thread with a traceback and take its session's events
        with it silently. Callers get one exception type they can report on.
        """
        try:
            with self._write_lock:
                self._conn.execute(statement, data)
                self._conn.commit()
        except sqlite3.Error as error:
            raise StorageError(f"Write to the database failed: {error}") from error

    def save_device(self, device: Device) -> None:
        """Stores a device, keeping the existing row if it is already known."""
        self._write(
            """
                INSERT INTO devices (
                    id, vendor_id, model_id, vendor_name, model_name, serial, interfaces
                ) VALUES (
                    :id, :vendor_id, :model_id, :vendor_name, :model_name, :serial, :interfaces
                )
                ON CONFLICT(id) DO NOTHING
            """,
            device.model_dump(),
        )

    def save_session(self, session: Session) -> None:
        """Stores a session, overwriting the features of an earlier write."""
        data = session.model_dump()
        data["id"] = str(data["id"])
        self._write(
            """
                INSERT INTO sessions (
                    id, device_id, connected_at, disconnected_at, event_count,
                    avg_interkey_delay_ms, std_interkey_delay_ms, min_interkey_delay_ms,
                    max_interkey_delay_ms, median_interkey_delay_ms,
                    avg_dwell_time_ms, std_dwell_time_ms,
                    backspace_count, max_keys_per_second, longest_burst_length,
                    time_to_first_keystroke_ms, launcher_hotkey_after_ms, keystroke_count
                ) VALUES (
                    :id, :device_id, :connected_at, :disconnected_at, :event_count,
                    :avg_interkey_delay_ms, :std_interkey_delay_ms, :min_interkey_delay_ms,
                    :max_interkey_delay_ms, :median_interkey_delay_ms,
                    :avg_dwell_time_ms, :std_dwell_time_ms,
                    :backspace_count, :max_keys_per_second, :longest_burst_length,
                    :time_to_first_keystroke_ms, :launcher_hotkey_after_ms, :keystroke_count
                )
                ON CONFLICT(id) DO UPDATE SET
                    disconnected_at = excluded.disconnected_at,
                    event_count = excluded.event_count,
                    avg_interkey_delay_ms = excluded.avg_interkey_delay_ms,
                    std_interkey_delay_ms = excluded.std_interkey_delay_ms,
                    min_interkey_delay_ms = excluded.min_interkey_delay_ms,
                    max_interkey_delay_ms = excluded.max_interkey_delay_ms,
                    median_interkey_delay_ms = excluded.median_interkey_delay_ms,
                    avg_dwell_time_ms = excluded.avg_dwell_time_ms,
                    std_dwell_time_ms = excluded.std_dwell_time_ms,
                    backspace_count = excluded.backspace_count,
                    max_keys_per_second = excluded.max_keys_per_second,
                    longest_burst_length = excluded.longest_burst_length,
                    time_to_first_keystroke_ms = excluded.time_to_first_keystroke_ms,
                    launcher_hotkey_after_ms = excluded.launcher_hotkey_after_ms,
                    keystroke_count = excluded.keystroke_count
            """,
            data,
        )

    def save_event(self, event: InputEvent) -> None:
        """Appends one raw input event to the session it belongs to."""
        data = event.model_dump()
        data["session_id"] = str(data["session_id"])
        self._write(
            """
                INSERT INTO input_events (session_id, type, code, value, timestamp)
                VALUES (:session_id, :type, :code, :value, :timestamp)
            """,
            data,
        )

    def save_detection(self, detection: Detection) -> None:
        """Upserts a session's verdict, keeping whichever was evaluated later.

        The scorer re-evaluates open sessions on a timer while handle_remove
        writes the final verdict, so the two can arrive out of order; the
        WHERE clause makes the newer evaluation win regardless.
        """
        data = detection.model_dump(mode="json")
        data["session_id"] = str(data["session_id"])
        data["reasons"] = json.dumps(data.pop("hits"))
        self._write(
            """
                INSERT INTO detections (session_id, score, verdict, reasons, evaluated_at)
                VALUES (:session_id, :score, :verdict, :reasons, :evaluated_at)
                ON CONFLICT (session_id) DO UPDATE SET
                score = excluded.score,
                verdict = excluded.verdict,
                reasons = excluded.reasons,
                evaluated_at = excluded.evaluated_at
                WHERE excluded.evaluated_at >= detections.evaluated_at
            """,
            data,
        )

    def _query(self, statement: str, params: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        """Runs one read statement, as a StorageError on failure.

        The dashboard reads on a timer from a second process; a database that
        has gone away under it should end with a message, not a traceback in
        the middle of a live view.
        """
        try:
            return self._conn.execute(statement, params).fetchall()
        except sqlite3.Error as error:
            raise StorageError(f"Read from the database failed: {error}") from error

    def get_session(self, session_id: UUID | str) -> Session | None:
        """The session with this id, or None if it was never stored."""
        rows = self._query("SELECT * FROM sessions WHERE id = ?", (str(session_id),))
        return Session(**dict(rows[0])) if rows else None

    def list_session(self, limit: int | None = None) -> list[Session]:
        """Stored sessions, newest first, optionally capped at limit rows.

        Raises:
            ValueError: limit is negative, which SQLite would silently read as
                'no limit at all' rather than reject.
        """
        if limit is not None and limit < 0:
            raise ValueError(f"limit must not be negative, got {limit}")

        query = "SELECT * FROM sessions ORDER BY connected_at DESC"
        params: tuple[object, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (limit,)
        return [Session(**dict(row)) for row in self._query(query, params)]

    def get_events_for_session(self, session_id: UUID | str, since_id: int = 0) -> list[InputEvent]:
        """Every raw event recorded for a session, in arrival order."""
        rows = self._query(
            """
            SELECT session_id, type, code, value, timestamp
            FROM input_events
            WHERE session_id = ? AND id > ?
            ORDER BY id
            """,
            (str(session_id), since_id),
        )
        return [InputEvent(**dict(row)) for row in rows]

    def get_device(self, device_id: str) -> Device | None:
        """The device with this id, or None if it was never seen."""
        rows = self._query("SELECT * FROM devices WHERE id = ?", (str(device_id),))
        return Device(**dict(rows[0])) if rows else None

    def list_devices(self) -> list[Device]:
        """Every device seen so far."""
        return [Device(**dict(row)) for row in self._query("SELECT * FROM devices")]

    def get_detection(self, session_id: UUID | str) -> Detection | None:
        """The current verdict for a session, or None if it was never scored."""
        rows = self._query("SELECT * FROM detections WHERE session_id = ?", (str(session_id),))
        return self._to_detection(rows[0]) if rows else None

    def list_detections(self) -> list[Detection]:
        """Every session's current verdict, most recently evaluated first."""
        rows = self._query("SELECT * FROM detections ORDER BY evaluated_at DESC")
        return [self._to_detection(row) for row in rows]

    @staticmethod
    def _to_detection(row: sqlite3.Row) -> Detection:
        """Rebuilds a Detection, unpacking the rule hits from their JSON column."""
        data = dict(row)
        data["hits"] = json.loads(data.pop("reasons"))
        return Detection(**data)

    def close(self) -> None:
        """Closes the connection.

        Runs from shutdown paths that must finish even when something already
        went wrong, so a failure to close is swallowed rather than raised: the
        process is ending and the WAL is recovered on the next open anyway.
        """
        with contextlib.suppress(sqlite3.Error):
            self._conn.close()
