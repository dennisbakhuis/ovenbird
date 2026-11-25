CREATE TABLE signal (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    unit TEXT,
    kind TEXT NOT NULL CHECK (kind IN ('number', 'enum', 'bool'))
);

CREATE TABLE sample (
    signal_id INTEGER NOT NULL REFERENCES signal (id),
    ts REAL NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (signal_id, ts)
) WITHOUT ROWID;

CREATE INDEX sample_ts ON sample (ts);

CREATE TABLE rollup (
    step INTEGER NOT NULL,
    signal_id INTEGER NOT NULL REFERENCES signal (id),
    bucket INTEGER NOT NULL,
    weighted_sum REAL NOT NULL,
    duration REAL NOT NULL,
    minimum REAL NOT NULL,
    maximum REAL NOT NULL,
    last REAL NOT NULL,
    last_ts REAL NOT NULL,
    PRIMARY KEY (step, signal_id, bucket)
) WITHOUT ROWID;

CREATE INDEX rollup_step_bucket ON rollup (step, bucket);
