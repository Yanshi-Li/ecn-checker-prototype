CREATE TABLE IF NOT EXISTS evaluation_sessions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tester_email TEXT NOT NULL,
    tester_name TEXT,
    task_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'completed', 'abandoned', 'timed_out')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS evaluation_batches (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES evaluation_sessions(id),
    status TEXT NOT NULL DEFAULT 'ACTIVE'
        CHECK (status IN ('ACTIVE', 'COMPLETED', 'COMPLETED_WITH_ERRORS', 'FAILED', 'CANCELLED')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS logical_ecns (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES evaluation_batches(id) ON DELETE CASCADE,
    logical_ecn_key TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (batch_id, logical_ecn_key)
);

CREATE TABLE IF NOT EXISTS bom_inputs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES evaluation_batches(id) ON DELETE CASCADE,
    bom_key TEXT NOT NULL,
    bom_state TEXT NOT NULL
        CHECK (bom_state IN ('ABSENT', 'EMPTY', 'PRESENT')),
    assigned_logical_ecn_id BIGINT REFERENCES logical_ecns(id),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (batch_id, bom_key)
);

CREATE TABLE IF NOT EXISTS precheck_cases (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES evaluation_batches(id) ON DELETE CASCADE,
    logical_ecn_id BIGINT NOT NULL REFERENCES logical_ecns(id),
    bom_input_id BIGINT REFERENCES bom_inputs(id),
    status TEXT NOT NULL DEFAULT 'NOT_RUN'
        CHECK (status IN ('PASS', 'FAIL', 'ERROR', 'NOT_RUN')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS precheck_attempts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES evaluation_sessions(id),
    case_id BIGINT REFERENCES precheck_cases(id),
    system_decision TEXT
        CHECK (system_decision IN ('PASS', 'FAIL')),

    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS evaluation_files (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL REFERENCES precheck_attempts(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('ecn', 'bom', 'other')),
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    captured_at TIMESTAMPTZ NOT NULL,
    content BYTEA NOT NULL
);

CREATE INDEX IF NOT EXISTS evaluation_files_attempt_idx
    ON evaluation_files (precheck_attempt_id);

CREATE TABLE IF NOT EXISTS evaluation_events (

    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES evaluation_sessions(id),
    precheck_attempt_id BIGINT REFERENCES precheck_attempts(id),
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS tester_judgements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL UNIQUE REFERENCES precheck_attempts(id),
    judgement TEXT NOT NULL CHECK (judgement IN ('PASS', 'FAIL')),
    explanation TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tester_rule_judgements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL REFERENCES precheck_attempts(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    judgement TEXT NOT NULL CHECK (judgement IN ('CORRECT', 'INCORRECT', 'UNCLEAR', 'NOT_APPLICABLE')),
    comment TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (precheck_attempt_id, rule_id)
);

CREATE TABLE IF NOT EXISTS app_users (

    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('TESTER', 'REVIEWER', 'ADMINISTRATOR')),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS review_assignments (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL REFERENCES precheck_attempts(id) ON DELETE CASCADE,
    reviewer_id BIGINT NOT NULL REFERENCES app_users(id),
    assigned_by BIGINT NOT NULL REFERENCES app_users(id),
    status TEXT NOT NULL DEFAULT 'ASSIGNED'
        CHECK (status IN ('ASSIGNED', 'IN_REVIEW', 'SUBMITTED', 'REVOKED')),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (precheck_attempt_id, reviewer_id)
);

CREATE TABLE IF NOT EXISTS reviewer_submissions (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL REFERENCES precheck_attempts(id) ON DELETE CASCADE,
    reviewer_id BIGINT NOT NULL REFERENCES app_users(id),
    overall_judgement TEXT NOT NULL CHECK (overall_judgement IN ('PASS', 'FAIL')),
    comment TEXT,
    status TEXT NOT NULL DEFAULT 'SUBMITTED'
        CHECK (status IN ('SUBMITTED', 'RESOLVED')),
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (precheck_attempt_id, reviewer_id)
);

CREATE TABLE IF NOT EXISTS reviewer_rule_judgements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    submission_id BIGINT NOT NULL REFERENCES reviewer_submissions(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    judgement TEXT NOT NULL CHECK (judgement IN ('CORRECT', 'INCORRECT', 'UNCLEAR', 'NOT_APPLICABLE')),
    comment TEXT,
    UNIQUE (submission_id, rule_id)
);

CREATE TABLE IF NOT EXISTS evaluation_review_status (
    precheck_attempt_id BIGINT PRIMARY KEY REFERENCES precheck_attempts(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'READY_FOR_REVIEW', 'IN_REVIEW', 'REVIEWED', 'DISPUTED')),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolution_comment TEXT,
    resolved_by BIGINT REFERENCES app_users(id),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS notification_attempts (

    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    precheck_attempt_id BIGINT NOT NULL REFERENCES precheck_attempts(id),
    notification_kind TEXT NOT NULL,
    recipient TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('requested', 'sent', 'failed')),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    error_message TEXT
);

ALTER TABLE precheck_attempts
    ADD COLUMN IF NOT EXISTS case_id BIGINT REFERENCES precheck_cases(id);

CREATE INDEX IF NOT EXISTS evaluation_events_session_idx
    ON evaluation_events (session_id, occurred_at);

CREATE INDEX IF NOT EXISTS precheck_attempts_session_idx
    ON precheck_attempts (session_id, started_at);

CREATE INDEX IF NOT EXISTS review_assignments_reviewer_idx
    ON review_assignments (reviewer_id, status);

CREATE INDEX IF NOT EXISTS reviewer_submissions_attempt_idx
    ON reviewer_submissions (precheck_attempt_id);

CREATE INDEX IF NOT EXISTS evaluation_review_status_status_idx
    ON evaluation_review_status (status);











