import json
import sqlite3
import threading
from pathlib import Path

from hidguard.models.detection import Detection
from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session
from hidguard.storage.schema import SCHEMA


class SqliteRepo:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._write_lock = threading.Lock()

    def save_device(self, device: Device) -> None:
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO devices (id, vendor_id, model_id, vendor_name, model_name, serial, interfaces)
                VALUES (:id, :vendor_id, :model_id, :vendor_name, :model_name, :serial, :interfaces)
                ON CONFLICT(id) DO NOTHING
                """,
                device.model_dump(),
            )
            self._conn.commit()

    def save_session(self, session: Session) -> None:
        data = session.model_dump()
        data["id"] = str(data["id"])
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    id, device_id, connected_at, disconnected_at, event_count,
                    avg_interkey_delay_ms, std_interkey_delay_ms, min_interkey_delay_ms,
                    max_interkey_delay_ms, median_interkey_delay_ms,
                    avg_dwell_time_ms, std_dwell_time_ms,
                    backspace_count, max_keys_per_second, longest_burst_length,
                    time_to_first_keystroke_ms
                ) VALUES (
                    :id, :device_id, :connected_at, :disconnected_at, :event_count,
                    :avg_interkey_delay_ms, :std_interkey_delay_ms, :min_interkey_delay_ms,
                    :max_interkey_delay_ms, :median_interkey_delay_ms,
                    :avg_dwell_time_ms, :std_dwell_time_ms,
                    :backspace_count, :max_keys_per_second, :longest_burst_length,
                    :time_to_first_keystroke_ms
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
                    time_to_first_keystroke_ms = excluded.time_to_first_keystroke_ms
                """,
                data,
            )
            self._conn.commit()

    
    def save_event(self, event: InputEvent) -> None:
        data = event.model_dump()
        data["session_id"] = str(data["session_id"])
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO input_events (session_id, type, code, value, timestamp)
                VALUES (:session_id, :type, :code, :value, :timestamp)
                """,
                data,
            )
            self._conn.commit()


    def save_detection(self, detection: Detection) -> None:
        data = detection.model_dump(mode="json")
        data["session_id"] = str(data["session_id"])
        data["reasons"] = json.dumps(data.pop("hits"))
        with self._write_lock:
            self._conn.execute(
                """
                INSERT INTO detections (session_id, score, verdict, reasons, evaluated_at)
                VALUES (:session_id, :score, :verdict, :reasons, :evaluated_at)
                ON CONFLICT (session_id) DO UPDATE SET
                score = excluded.score,
                verdict = excluded.verdict,
                reasons = excludded.reasons,
                evauluated_at = excluded.evaluated_at,
                """,
                data
            )
            self._conn.commit()


    def get_session(self, session_id) -> Session | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE ID = ?", (str(session_id),)
        ).fetchone()
        return Session(**dict(row)) if row else None

    def list_session(self, limit: int | None = None) -> list[Session]:
        query = "SELECT * FROM sessions ORDER BY connected_at DESC"
        params = tuple()
        if limit is not None:
            query += "LIMIT ?"
            params = (limit,)
        rows = self._conn.execute(query, params).fetchall()
        return [Session(**dict(row)) for row in rows]

    def get_events_for_session(self, session_id, since_id: int = 0) -> list[InputEvent]:
        rows= self._conn.execute(
            """
            SELECT session_id, type, code, value, timestamp
            FROM input_events
            WHERE session_id = ? AND id > ?
            ORDER BY id
            """,
            (str(session_id), since_id)
        ).fetchall()
        return [InputEvent(**dict(row)) for row in rows]

    def get_device(self, device_id) -> Device | None:
        row = self._conn.execute(
            """
            SELECT * FROM devices
            WHERE device_id = ?
            """,
            str(device_id)
        ).fetchall()
        return Device(**dict(row)) if row else None

    def list_devices(self) -> list[Device]:
        rows = self._conn.execute("SELECT * FROM devices").fetchall()
        return [Device(**dict(row)) for row in rows]

    def get_detection(self, session_id) -> Detection | None:
        row = self._conn.execute(
            """
            SELECT * FROM detections WHERE session_id = ?
            """,
            str(session_id)
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["hits"] = json.loads(data.pop("reasons"))
        return Detection(**data)

    def list_detections(self) -> list[Detection]:
        rows = self._conn.execute(
            """
            SELECT * FROM detection ORDER BY evaluated_at DESC
            """
        ).fetchall()
        results = []
        for row in rows:
            data = dict(row)
            data["hits"] = json.loads(data.pop("reasons"))
            results.append(Detection(**dict(data)))

        return results

    def close(self) -> None:
        self._conn.close()