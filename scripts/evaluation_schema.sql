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

CREATE TABLE IF NOT EXISTS precheck_attempts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    session_id BIGINT NOT NULL REFERENCES evaluation_sessions(id),
    system_decision TEXT
        CHECK (system_decision IN ('PASS', 'FAIL')),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    result_payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

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

CREATE INDEX IF NOT EXISTS evaluation_events_session_idx
    ON evaluation_events (session_id, occurred_at);

CREATE INDEX IF NOT EXISTS precheck_attempts_session_idx
    ON precheck_attempts (session_id, started_at);
