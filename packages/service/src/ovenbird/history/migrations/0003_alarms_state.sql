CREATE TABLE alarm (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE INDEX alarm_ts ON alarm (ts);

CREATE TABLE control_state (
    key TEXT PRIMARY KEY,
    ts REAL NOT NULL,
    value TEXT NOT NULL
);
