from datetime import datetime
from pydantic import BaseModel

class Session(BaseModel):
    id: str
    device_id: str
    connected_at: datetime
    disconnected_at: datetime | None = None
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

