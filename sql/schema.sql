-- talent-analytics-sql: schema (SQLite 3.35+)
--
-- Star-style model for talent acquisition and workforce analytics.
-- Conventions
--   * All dates are ISO-8601 text ('YYYY-MM-DD'). They sort and compare correctly
--     as text and join to dim_date.full_date.
--   * Surrogate integer keys. Foreign keys are enforced (PRAGMA foreign_keys=ON).
--   * Business rules that a single row can prove are CHECK constraints.
--     Rules that need several rows are checked by sql/queries/21_data_quality_checks.sql.
--   * Secondary indexes live in sql/indexes.sql so they can be added and dropped
--     for the before/after benchmark (see docs/PERFORMANCE.md).

PRAGMA foreign_keys = ON;

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Calendar dimension. Facts store plain dates; dim_date adds year/quarter/month attributes.
CREATE TABLE dim_date (
    date_key     INTEGER PRIMARY KEY,                 -- yyyymmdd
    full_date    TEXT    NOT NULL UNIQUE,
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL CHECK (quarter BETWEEN 1 AND 4),
    month        INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    day_of_month INTEGER NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    day_of_week  INTEGER NOT NULL CHECK (day_of_week BETWEEN 0 AND 6),  -- 0 = Sunday
    is_weekend   INTEGER NOT NULL CHECK (is_weekend IN (0, 1))
);

-- Reference data: the fixed stages of the hiring pipeline.
CREATE TABLE dim_stage (
    stage_order INTEGER PRIMARY KEY CHECK (stage_order BETWEEN 1 AND 5),
    stage_name  TEXT    NOT NULL UNIQUE,
    UNIQUE (stage_order, stage_name)
);

INSERT INTO dim_stage (stage_order, stage_name) VALUES
    (1, 'Applied'),
    (2, 'Recruiter Screen'),
    (3, 'Hiring Manager Screen'),
    (4, 'Onsite'),
    (5, 'Offer');

CREATE TABLE dim_recruiter (
    recruiter_id INTEGER PRIMARY KEY,
    full_name    TEXT NOT NULL,
    team         TEXT NOT NULL,
    start_date   TEXT NOT NULL
);

CREATE TABLE dim_employee (
    employee_id          INTEGER PRIMARY KEY,
    full_name            TEXT    NOT NULL,
    manager_id           INTEGER REFERENCES dim_employee (employee_id),
    team                 TEXT    NOT NULL,
    level                INTEGER NOT NULL CHECK (level BETWEEN 1 AND 8),
    location             TEXT    NOT NULL,
    gender               TEXT    NOT NULL CHECK (gender IN ('F', 'M', 'X')),
    demographic_group    TEXT    NOT NULL CHECK (demographic_group IN ('G1', 'G2', 'G3', 'G4')),
    hire_date            TEXT    NOT NULL,
    term_date            TEXT,                         -- NULL = still employed
    term_reason          TEXT    CHECK (term_reason IN ('voluntary', 'involuntary')),
    source_application_id INTEGER UNIQUE REFERENCES fact_application (application_id),
    CHECK (manager_id IS NULL OR manager_id <> employee_id),
    CHECK (term_date IS NULL OR term_date >= hire_date),
    CHECK ((term_date IS NULL) = (term_reason IS NULL))
);

CREATE TABLE dim_requisition (
    requisition_id    INTEGER PRIMARY KEY,
    role_title        TEXT    NOT NULL,
    team              TEXT    NOT NULL,
    level             INTEGER NOT NULL CHECK (level BETWEEN 1 AND 8),
    location          TEXT    NOT NULL,
    recruiter_id      INTEGER NOT NULL REFERENCES dim_recruiter (recruiter_id),
    hiring_manager_id INTEGER REFERENCES dim_employee (employee_id),
    opened_date       TEXT    NOT NULL,
    closed_date       TEXT,
    status            TEXT    NOT NULL CHECK (status IN ('open', 'filled', 'cancelled')),
    CHECK (closed_date IS NULL OR closed_date >= opened_date),
    CHECK ((status = 'open') = (closed_date IS NULL))
);

CREATE TABLE dim_candidate (
    candidate_id      INTEGER PRIMARY KEY,
    full_name         TEXT NOT NULL,
    email             TEXT NOT NULL,
    gender            TEXT NOT NULL CHECK (gender IN ('F', 'M', 'X')),
    demographic_group TEXT NOT NULL CHECK (demographic_group IN ('G1', 'G2', 'G3', 'G4'))
);

CREATE TABLE fact_application (
    application_id INTEGER PRIMARY KEY,
    candidate_id   INTEGER NOT NULL REFERENCES dim_candidate (candidate_id),
    requisition_id INTEGER NOT NULL REFERENCES dim_requisition (requisition_id),
    source         TEXT    NOT NULL CHECK (source IN
                       ('Referral', 'LinkedIn', 'Career Site', 'Job Board', 'Agency', 'Campus')),
    applied_at     TEXT    NOT NULL,
    UNIQUE (candidate_id, requisition_id)
);

-- One row per stage an application entered. outcome = 'open' means the stage is in progress.
CREATE TABLE fact_stage_event (
    event_id       INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES fact_application (application_id),
    stage_order    INTEGER NOT NULL,
    stage          TEXT    NOT NULL,
    entered_at     TEXT    NOT NULL,
    exited_at      TEXT,
    outcome        TEXT    NOT NULL CHECK (outcome IN ('advanced', 'rejected', 'withdrawn', 'open')),
    UNIQUE (application_id, stage_order),
    FOREIGN KEY (stage_order, stage) REFERENCES dim_stage (stage_order, stage_name),
    CHECK (exited_at IS NULL OR exited_at >= entered_at),
    CHECK ((outcome = 'open') = (exited_at IS NULL))
);

CREATE TABLE fact_offer (
    offer_id       INTEGER PRIMARY KEY,
    application_id INTEGER NOT NULL UNIQUE REFERENCES fact_application (application_id),
    extended_date  TEXT    NOT NULL,
    decided_date   TEXT,
    status         TEXT    NOT NULL CHECK (status IN ('accepted', 'declined', 'expired', 'pending')),
    base_salary    INTEGER NOT NULL CHECK (base_salary > 0),
    start_date     TEXT,
    CHECK (decided_date IS NULL OR decided_date >= extended_date),
    CHECK ((status = 'pending') = (decided_date IS NULL)),
    CHECK ((status = 'accepted') = (start_date IS NOT NULL))
);

-- Continuous employment periods. A person with a leave or a re-hire has several rows.
CREATE TABLE fact_employment_spell (
    spell_id    INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES dim_employee (employee_id),
    start_date  TEXT    NOT NULL,
    end_date    TEXT,                                   -- NULL = ongoing
    UNIQUE (employee_id, start_date),
    CHECK (end_date IS NULL OR end_date >= start_date)
);

CREATE TABLE fact_compensation_snapshot (
    employee_id      INTEGER NOT NULL REFERENCES dim_employee (employee_id),
    effective_date   TEXT    NOT NULL,
    base_salary      INTEGER NOT NULL CHECK (base_salary > 0),
    level            INTEGER NOT NULL CHECK (level BETWEEN 1 AND 8),
    bonus_target_pct INTEGER NOT NULL CHECK (bonus_target_pct BETWEEN 0 AND 100),
    PRIMARY KEY (employee_id, effective_date)
);

CREATE TABLE fact_performance_review (
    review_id   INTEGER PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES dim_employee (employee_id),
    cycle_year  INTEGER NOT NULL,
    review_date TEXT    NOT NULL,
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    reviewer_id INTEGER REFERENCES dim_employee (employee_id),
    UNIQUE (employee_id, cycle_year)
);
