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

ALTER TABLE precheck_attempts
    ADD COLUMN IF NOT EXISTS case_id BIGINT REFERENCES precheck_cases(id);

CREATE INDEX IF NOT EXISTS evaluation_events_session_idx
    ON evaluation_events (session_id, occurred_at);

CREATE INDEX IF NOT EXISTS precheck_attempts_session_idx
    ON precheck_attempts (session_id, started_at);
