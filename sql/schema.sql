-- OPSPULSE database schema (SQLite)
-- Three related tables: a lookup table for priorities, one for assignment
-- groups, and the main incidents table that points to both.

DROP TABLE IF EXISTS incidents;
DROP TABLE IF EXISTS priorities;
DROP TABLE IF EXISTS assignment_groups;

CREATE TABLE priorities (
    priority         TEXT PRIMARY KEY,      -- P1..P4
    sla_target_hours INTEGER NOT NULL
);

CREATE TABLE assignment_groups (
    group_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    group_name TEXT NOT NULL UNIQUE
);

CREATE TABLE incidents (
    incident_id       TEXT PRIMARY KEY,
    opened_at         TEXT NOT NULL,        -- ISO date text: YYYY-MM-DD HH:MM:SS
    resolved_at       TEXT,                 -- NULL while the ticket is still open
    priority          TEXT NOT NULL REFERENCES priorities(priority),
    category          TEXT NOT NULL,
    subcategory       TEXT,
    group_id          INTEGER NOT NULL REFERENCES assignment_groups(group_id),
    assigned_to       TEXT,
    caller_department TEXT,
    location          TEXT,
    state             TEXT NOT NULL,
    reopen_count      INTEGER DEFAULT 0,
    short_description TEXT,
    bad_dates         INTEGER NOT NULL DEFAULT 0,   -- 1 = resolved before opened
    resolution_hours  REAL,                         -- NULL for open or bad rows
    sla_met           INTEGER                       -- 1 yes, 0 no, NULL unknown
);

CREATE INDEX idx_incidents_opened   ON incidents(opened_at);
CREATE INDEX idx_incidents_priority ON incidents(priority);
CREATE INDEX idx_incidents_group    ON incidents(group_id);
