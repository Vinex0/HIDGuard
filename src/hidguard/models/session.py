from __future__ import annotations

import time
from uuid import UUID, uuid4

from pydantic import BaseModel


class Session(BaseModel):
    id: UUID
    device_id: str
    connected_at: float
    disconnected_at: float | None = None
    event_count: int = 0

    # Interkey delay
    avg_interkey_delay_ms: float | None = None
    std_interkey_delay_ms: float | None = None
    min_interkey_delay_ms: float | None = None
    max_interkey_delay_ms: float | None = None
    median_interkey_delay_ms: float | None = None

    # Dwell time
    avg_dwell_time_ms: float | None = None
    std_dwell_time_ms: float | None = None

    # Fehlerkorrektur
    backspace_count: int = 0

    # Burst-Verhalten
    max_keys_per_second: int | None = None
    longest_burst_length: int | None = None

    # Kontext
    time_to_first_keystroke_ms: float | None = None
    launcher_hotkey_after_ms: float | None = None
    keystroke_count: int = 0

    @classmethod
    def start(cls, device_id: str) -> Session:
        return cls(id=uuid4(), device_id=device_id, connected_at=time.time())

    def end(self) -> None:
        self.disconnected_at = time.time()
