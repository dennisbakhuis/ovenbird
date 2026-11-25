CREATE TABLE config_version (
    version INTEGER PRIMARY KEY,
    created_ts REAL NOT NULL,
    actor TEXT NOT NULL,
    source_ip TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('ui', 'rollback', 'seed', 'reset')),
    comment TEXT,
    parent INTEGER,
    doc TEXT NOT NULL,
    doc_hash TEXT NOT NULL,
    applied_ts REAL
);

CREATE TRIGGER config_version_append_only
BEFORE UPDATE OF version, created_ts, actor, source_ip, origin, comment, parent, doc, doc_hash
ON config_version
BEGIN
    SELECT RAISE(ABORT, 'config_version is append-only');
END;

CREATE TRIGGER config_version_no_delete
BEFORE DELETE ON config_version
BEGIN
    SELECT RAISE(ABORT, 'config_version is append-only');
END;

CREATE TABLE audit (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    source_ip TEXT,
    action TEXT NOT NULL,
    detail TEXT NOT NULL
);

CREATE INDEX audit_ts ON audit (ts);

CREATE TRIGGER audit_no_update
BEFORE UPDATE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit is append-only');
END;

CREATE TRIGGER audit_no_delete
BEFORE DELETE ON audit
BEGIN
    SELECT RAISE(ABORT, 'audit is append-only');
END;

CREATE TABLE runtime (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
