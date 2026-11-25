CREATE TABLE forecast (
    issued_ts REAL NOT NULL,
    target_ts REAL NOT NULL,
    temp_c REAL,
    radiation_wm2 REAL,
    cloud_pct REAL,
    wind_ms REAL,
    PRIMARY KEY (issued_ts, target_ts)
) WITHOUT ROWID;

CREATE INDEX forecast_target ON forecast (target_ts);
