SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    vendor_id TEXT,
    model_id TEXT,
    vendor_name TEXT,
    model_name TEXT,
    serial TEXT,
    interfaces TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    connected_at REAL NOT NULL,
    disconnected_at REAL,
    event_count INTEGER NOT NULL DEFAULT 0,
    avg_interkey_delay_ms REAL,
    std_interkey_delay_ms REAL,
    min_interkey_delay_ms REAL,
    max_interkey_delay_ms REAL,
    median_interkey_delay_ms REAL,
    avg_dwell_time_ms REAL,
    std_dwell_time_ms REAL,
    backspace_count INTEGER NOT NULL DEFAULT 0,
    max_keys_per_second INTEGER,
    longest_burst_length INTEGER,
    time_to_first_keystroke_ms REAL,
    FOREIGN KEY (device_id) REFERENCES devices(id)
); 

CREATE TABLE IF NOT EXISTS input_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    type INTEGER NOT NULL,
    code INTEGER NOT NULL,
    value INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_input_events_session ON input_events(session_id, id);

CREATE TABLE IF NOT EXISTS detections (
    session_id TEXT PRIMARY KEY,
    score INTEGER NOT NULL,
    verdict TEXT NOT NULL,
    reasons TEXT NOT NULL,
    evaluated_at REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""