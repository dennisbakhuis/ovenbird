CREATE TABLE decision (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    controller TEXT NOT NULL,
    mode TEXT NOT NULL,
    ladder TEXT NOT NULL,
    reason TEXT NOT NULL,
    setpoint INTEGER,
    record TEXT NOT NULL,
    arbiter TEXT NOT NULL,
    commands TEXT NOT NULL
);

CREATE INDEX decision_ts ON decision (ts);

CREATE TABLE command (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    value INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempt INTEGER NOT NULL,
    topic TEXT,
    payload TEXT,
    detail TEXT NOT NULL
);

CREATE INDEX command_ts ON command (ts);
