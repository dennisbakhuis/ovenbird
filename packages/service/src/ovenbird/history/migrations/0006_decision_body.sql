CREATE TABLE decision_dictionary (
    id INTEGER PRIMARY KEY,
    created_ts REAL NOT NULL,
    data BLOB NOT NULL
);

INSERT INTO decision_dictionary (created_ts, data)
SELECT ts, ovenbird_dictionary(record, arbiter)
FROM decision
ORDER BY ts DESC, id DESC
LIMIT 1;

CREATE TABLE decision_packed (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    controller TEXT NOT NULL,
    mode TEXT NOT NULL,
    ladder TEXT NOT NULL,
    reason TEXT NOT NULL,
    setpoint INTEGER,
    config_version INTEGER,
    dictionary_id INTEGER REFERENCES decision_dictionary (id),
    body BLOB NOT NULL
);

INSERT INTO decision_packed
    (id, ts, controller, mode, ladder, reason, setpoint, config_version, dictionary_id, body)
SELECT
    id, ts, controller, mode, ladder, reason, setpoint, config_version,
    (SELECT max(id) FROM decision_dictionary),
    ovenbird_pack(
        record, arbiter, commands,
        (SELECT data FROM decision_dictionary ORDER BY id DESC LIMIT 1)
    )
FROM decision
ORDER BY id;

DROP TABLE decision;

ALTER TABLE decision_packed RENAME TO decision;

CREATE INDEX decision_ts ON decision (ts);
