import sqlite3
from pathlib import Path

from hidguard.models.device_model import Device
from hidguard.models.input_event import InputEvent
from hidguard.models.session import Session
from hidguard.storage.schema import SCHEMA


class SqliteRepo:
    def __init__(self, db_path: str | Path):
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def save_device(self, device: Device) -> None:
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
        self._conn.execute(
            """
            INSERT INTO input_events (session_id, type, code, value, timestamp)
            VALUES (:session_id, :type, :code, :value, :timestamp)
            """,
            data,
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()