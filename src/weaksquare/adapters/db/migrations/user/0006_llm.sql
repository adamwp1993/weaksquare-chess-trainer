-- user.db v6 (v0.7): LLM Explain and the cost guardrails (REQUIREMENTS §9.3). Never edit this file once
-- applied; add 0007_… instead. New tables only.

-- The editable price table (FR-8.9), USD per 1M tokens. The long-context tier applies when a request's
-- input tokens exceed `long_ctx_threshold` (NULL: no tier). Rows are seeded by the app from
-- core/llm/defaults.py (the only place model names live), never by this file.
CREATE TABLE llm_prices (
    provider           TEXT NOT NULL,
    model              TEXT NOT NULL,
    input_per_m        REAL NOT NULL,
    output_per_m       REAL NOT NULL,
    long_ctx_threshold INTEGER,
    long_input_per_m   REAL,
    long_output_per_m  REAL,
    as_of              TEXT NOT NULL,
    PRIMARY KEY (provider, model)
);

-- One row per provider response that reported usage (FR-8.10). `status` is ok, truncated (hit
-- max_tokens) or refused. `local_month` (YYYY-MM) is the calendar month where you are when the request
-- was made: the monthly budget (FR-8.13) sums `cost_usd` over it.
CREATE TABLE llm_usage (
    id            INTEGER PRIMARY KEY,
    ts            TEXT NOT NULL,
    local_month   TEXT NOT NULL,
    feature       TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      REAL NOT NULL,
    status        TEXT NOT NULL
);

CREATE INDEX llm_usage_month ON llm_usage (local_month);

-- Explain results (FR-8.6), keyed by a SHA-256 of (puzzle_id, your move path, provider, model). The
-- validated result is stored, so a cache hit is free and needs no second validation.
CREATE TABLE llm_cache (
    key           TEXT PRIMARY KEY,
    provider      TEXT NOT NULL,
    model         TEXT NOT NULL,
    response_json TEXT NOT NULL,
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    created_at    TEXT NOT NULL
);
