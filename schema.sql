PRAGMA foreign_keys = ON;

-- Persist only source records, benchmark metadata, run lineage and model output.
-- Business-facing attributes and metrics are calculated by the views below.
CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT NOT NULL PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    headquarters TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    job_title TEXT NOT NULL,
    raw_department TEXT NOT NULL,
    raw_team TEXT NOT NULL,
    location TEXT NOT NULL,
    work_email TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    PRIMARY KEY (company_id, employee_id),
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

CREATE TABLE IF NOT EXISTS inference_runs (
    run_id TEXT NOT NULL PRIMARY KEY,
    source_hash TEXT NOT NULL UNIQUE CHECK (length(source_hash) = 64),
    model_version TEXT NOT NULL,
    pipeline_version TEXT NOT NULL,
    model_type TEXT NOT NULL,
    probability_threshold REAL NOT NULL CHECK (probability_threshold BETWEEN 0 AND 1),
    margin_threshold REAL NOT NULL CHECK (margin_threshold BETWEEN 0 AND 1),
    source_company_count INTEGER NOT NULL CHECK (source_company_count > 0),
    source_employee_count INTEGER NOT NULL CHECK (source_employee_count > 0),
    load_status TEXT NOT NULL CHECK (load_status IN ('loading', 'ready')),
    loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

-- One durable row per model decision. Feature, prediction and explanation views
-- expose different business grains without copying the same result repeatedly.
CREATE TABLE IF NOT EXISTS inference_outputs (
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    inferred_department TEXT NOT NULL,
    inferred_level TEXT NOT NULL,
    inferred_rank INTEGER NOT NULL CHECK (inferred_rank BETWEEN 0 AND 10),
    accepted_manager_id TEXT,
    best_candidate_id TEXT,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    margin REAL NOT NULL CHECK (margin BETWEEN 0 AND 1 AND margin <= confidence),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'unresolved', 'company_root')),
    reasons_json TEXT NOT NULL CHECK (json_valid(reasons_json) AND json_type(reasons_json) = 'array'),
    PRIMARY KEY (run_id, company_id, employee_id),
    CHECK (accepted_manager_id IS NULL OR accepted_manager_id <> employee_id),
    CHECK (best_candidate_id IS NULL OR best_candidate_id <> employee_id),
    CHECK (
        (decision = 'accepted' AND accepted_manager_id IS NOT NULL
            AND best_candidate_id IS NOT NULL AND accepted_manager_id = best_candidate_id)
        OR (decision IN ('unresolved', 'company_root') AND accepted_manager_id IS NULL)
    ),
    FOREIGN KEY (run_id) REFERENCES inference_runs (run_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, employee_id),
    FOREIGN KEY (company_id, accepted_manager_id) REFERENCES employees (company_id, employee_id),
    FOREIGN KEY (company_id, best_candidate_id) REFERENCES employees (company_id, employee_id)
);

CREATE INDEX IF NOT EXISTS outputs_by_manager
    ON inference_outputs (run_id, company_id, accepted_manager_id)
    WHERE accepted_manager_id IS NOT NULL;

-- Imported labels are a fixed answer key from the dataset generator. They are
-- never inferred from model output; doing so would invalidate evaluation.
CREATE TABLE IF NOT EXISTS benchmark_labels (
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    manager_employee_id TEXT,
    canonical_title TEXT NOT NULL,
    canonical_department TEXT NOT NULL,
    canonical_team TEXT NOT NULL,
    canonical_level TEXT NOT NULL,
    is_people_manager INTEGER NOT NULL CHECK (is_people_manager IN (0, 1)),
    noise_profile_json TEXT NOT NULL
        CHECK (json_valid(noise_profile_json) AND json_type(noise_profile_json) = 'array'),
    PRIMARY KEY (company_id, employee_id),
    CHECK (manager_employee_id IS NULL OR manager_employee_id <> employee_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, employee_id),
    FOREIGN KEY (company_id, manager_employee_id) REFERENCES employees (company_id, employee_id)
);

-- The benchmark shape is calculated from source labels; root status is not
-- copied into another stored column.
CREATE VIEW IF NOT EXISTS benchmark_truth AS
SELECT
    company_id, employee_id, manager_employee_id,
    canonical_title, canonical_department, canonical_team, canonical_level,
    is_people_manager,
    CASE WHEN manager_employee_id IS NULL THEN 1 ELSE 0 END AS is_root,
    noise_profile_json
FROM benchmark_labels;

-- Dynamic company attributes. Headcount and size band always reflect employees.
CREATE VIEW IF NOT EXISTS company_profiles AS
SELECT
    c.company_id,
    c.company_name,
    c.industry,
    CASE
        WHEN count(e.employee_id) < 130 THEN 'Small'
        WHEN count(e.employee_id) < 180 THEN 'Growth'
        ELSE 'Mid-market'
    END AS size_band,
    count(e.employee_id) AS employee_count,
    c.headquarters
FROM companies AS c
LEFT JOIN employees AS e USING (company_id)
GROUP BY c.company_id, c.company_name, c.industry, c.headquarters;

-- Every employee appears for every ready run. A newly inserted raw employee is
-- visible immediately as pending instead of silently disappearing from reports.
CREATE VIEW IF NOT EXISTS employee_features AS
SELECT
    r.run_id,
    e.company_id,
    e.employee_id,
    coalesce(o.inferred_department, 'Unclassified') AS inferred_department,
    coalesce(o.inferred_level, 'Unknown') AS inferred_level,
    coalesce(o.inferred_rank, 1) AS inferred_rank,
    CASE WHEN o.employee_id IS NULL THEN 'pending_inference' ELSE 'processed' END AS processing_status
FROM inference_runs AS r
CROSS JOIN employees AS e
LEFT JOIN inference_outputs AS o
    ON o.run_id = r.run_id
    AND o.company_id = e.company_id
    AND o.employee_id = e.employee_id
WHERE r.load_status = 'ready';

CREATE VIEW IF NOT EXISTS reporting_predictions AS
SELECT
    r.run_id,
    e.company_id,
    e.employee_id,
    o.accepted_manager_id,
    o.best_candidate_id,
    coalesce(o.confidence, 0.0) AS confidence,
    coalesce(o.margin, 0.0) AS margin,
    coalesce(o.decision, 'pending_inference') AS decision
FROM inference_runs AS r
CROSS JOIN employees AS e
LEFT JOIN inference_outputs AS o
    ON o.run_id = r.run_id
    AND o.company_id = e.company_id
    AND o.employee_id = e.employee_id
WHERE r.load_status = 'ready';

-- Evaluation is a live comparison, not a stored copy of a prediction/result.
-- An employee without a generated label is visibly unevaluated.
CREATE VIEW IF NOT EXISTS benchmark_comparison AS
SELECT
    p.run_id, p.company_id, p.employee_id,
    p.accepted_manager_id, p.confidence, p.decision,
    b.manager_employee_id AS expected_manager_id,
    CASE
        WHEN b.employee_id IS NULL THEN 'unlabeled'
        WHEN p.decision <> 'accepted' THEN 'not_accepted'
        WHEN p.accepted_manager_id = b.manager_employee_id THEN 'correct'
        ELSE 'incorrect'
    END AS evaluation_status
FROM reporting_predictions AS p
LEFT JOIN benchmark_truth AS b USING (company_id, employee_id);

CREATE VIEW IF NOT EXISTS prediction_reasons AS
SELECT
    o.run_id,
    o.company_id,
    o.employee_id,
    reason.key AS position,
    reason.value AS reason
FROM inference_outputs AS o
JOIN json_each(o.reasons_json) AS reason;

CREATE VIEW IF NOT EXISTS employee_noise AS
SELECT
    t.company_id,
    t.employee_id,
    noise.key AS position,
    noise.value AS noise_type
FROM benchmark_truth AS t
JOIN json_each(t.noise_profile_json) AS noise;

-- Metrics are calculated from employee-level rows, never copied from an export.
-- Pending employees lower coverage until the inference pipeline processes them.
CREATE VIEW IF NOT EXISTS company_run_metrics AS
WITH employee_metrics AS (
    SELECT
        p.run_id,
        p.company_id,
        sum(p.decision = 'accepted') AS resolved_count,
        sum(p.decision IN ('unresolved', 'pending_inference')) AS unresolved_count,
        1.0 * sum(p.decision = 'accepted') /
            max(sum(p.decision <> 'company_root'), 1) AS coverage_raw,
        coalesce(avg(CASE WHEN p.decision = 'accepted' THEN p.confidence END), 0.0)
            AS average_confidence_raw
    FROM reporting_predictions AS p
    GROUP BY p.run_id, p.company_id
), benchmark_metrics AS (
    SELECT
        run_id, company_id,
        1.0 * sum(evaluation_status = 'correct') /
            max(sum(evaluation_status IN ('correct', 'incorrect')), 1) AS precision_raw
    FROM benchmark_comparison
    GROUP BY run_id, company_id
)
SELECT
    e.run_id,
    e.company_id,
    e.resolved_count,
    e.unresolved_count,
    cast(e.coverage_raw * 10000.0 + 0.5000000001 AS INTEGER) / 10000.0 AS coverage,
    cast(b.precision_raw * 10000.0 + 0.5000000001 AS INTEGER) / 10000.0 AS precision,
    cast(e.average_confidence_raw * 10000.0 + 0.5000000001 AS INTEGER) / 10000.0
        AS average_confidence
FROM employee_metrics AS e
JOIN benchmark_metrics AS b USING (run_id, company_id);

CREATE VIEW IF NOT EXISTS run_metrics AS
WITH run_totals AS (
    SELECT
        run_id,
        count(DISTINCT company_id) AS company_count,
        count(*) AS employee_count,
        sum(decision = 'accepted') AS accepted_count,
        sum(decision IN ('unresolved', 'pending_inference')) AS unresolved_count,
        sum(decision = 'pending_inference') AS pending_inference_count,
        coalesce(avg(CASE WHEN decision = 'accepted' THEN confidence END), 0.0)
            AS average_resolved_confidence_raw
    FROM reporting_predictions
    GROUP BY run_id
)
SELECT
    run_id,
    company_count,
    employee_count,
    accepted_count,
    unresolved_count,
    pending_inference_count,
    cast(average_resolved_confidence_raw * 10000.0 + 0.5000000001 AS INTEGER) / 10000.0
        AS average_resolved_confidence
FROM run_totals;

-- One inspectable decision per employee and run. The answer key is deliberately absent.
CREATE VIEW IF NOT EXISTS employee_reporting_audit AS
SELECT
    p.run_id, e.company_id, e.employee_id, e.full_name, e.job_title,
    e.raw_department, e.raw_team, e.location,
    f.inferred_department, f.inferred_level, f.processing_status,
    p.accepted_manager_id, manager.full_name AS inferred_manager,
    p.best_candidate_id, candidate.full_name AS leading_candidate,
    p.confidence, p.margin, p.decision,
    r.probability_threshold, r.margin_threshold,
    CASE
        WHEN p.decision = 'pending_inference' THEN 'pending_inference'
        WHEN p.decision = 'company_root' THEN 'observed_ceo_title'
        WHEN p.decision = 'accepted' THEN 'cleared_both_checks'
        WHEN p.best_candidate_id IS NULL THEN 'no_suitable_candidate'
        WHEN p.confidence < r.probability_threshold AND p.margin < r.margin_threshold
            THEN 'low_confidence_and_ambiguous_candidates'
        WHEN p.confidence < r.probability_threshold THEN 'low_confidence'
        WHEN p.margin < r.margin_threshold THEN 'ambiguous_candidates'
        ELSE 'unresolved'
    END AS decision_reason,
    r.source_hash, r.model_version, r.pipeline_version
FROM reporting_predictions AS p
JOIN inference_runs AS r USING (run_id)
JOIN employees AS e USING (company_id, employee_id)
JOIN employee_features AS f USING (run_id, company_id, employee_id)
LEFT JOIN employees AS manager
    ON manager.company_id = p.company_id AND manager.employee_id = p.accepted_manager_id
LEFT JOIN employees AS candidate
    ON candidate.company_id = p.company_id AND candidate.employee_id = p.best_candidate_id;
