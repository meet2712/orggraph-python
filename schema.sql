PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    company_id TEXT NOT NULL PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    size_band TEXT NOT NULL,
    employee_count INTEGER NOT NULL CHECK (employee_count > 0),
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
    loaded_company_count INTEGER NOT NULL DEFAULT 0 CHECK (loaded_company_count >= 0),
    loaded_employee_count INTEGER NOT NULL DEFAULT 0 CHECK (loaded_employee_count >= 0),
    loaded_prediction_count INTEGER NOT NULL DEFAULT 0 CHECK (loaded_prediction_count >= 0),
    accepted_prediction_count INTEGER NOT NULL DEFAULT 0 CHECK (accepted_prediction_count >= 0),
    load_status TEXT NOT NULL CHECK (load_status IN ('loading', 'ready')),
    loaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS employee_features (
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    inferred_department TEXT NOT NULL,
    inferred_level TEXT NOT NULL,
    inferred_rank INTEGER NOT NULL CHECK (inferred_rank BETWEEN 0 AND 8),
    PRIMARY KEY (run_id, company_id, employee_id),
    FOREIGN KEY (run_id) REFERENCES inference_runs (run_id),
    FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, employee_id)
);

CREATE TABLE IF NOT EXISTS reporting_predictions (
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    accepted_manager_id TEXT,
    best_candidate_id TEXT,
    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    margin REAL NOT NULL CHECK (margin BETWEEN 0 AND 1 AND margin <= confidence),
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'unresolved', 'company_root')),
    PRIMARY KEY (run_id, company_id, employee_id),
    CHECK (accepted_manager_id IS NULL OR accepted_manager_id <> employee_id),
    CHECK (best_candidate_id IS NULL OR best_candidate_id <> employee_id),
    CHECK (
        (decision = 'accepted' AND accepted_manager_id IS NOT NULL
            AND best_candidate_id IS NOT NULL AND accepted_manager_id = best_candidate_id)
        OR (decision IN ('unresolved', 'company_root') AND accepted_manager_id IS NULL)
    ),
    FOREIGN KEY (run_id, company_id, employee_id)
        REFERENCES employee_features (run_id, company_id, employee_id),
    FOREIGN KEY (run_id, company_id, accepted_manager_id)
        REFERENCES employee_features (run_id, company_id, employee_id),
    FOREIGN KEY (run_id, company_id, best_candidate_id)
        REFERENCES employee_features (run_id, company_id, employee_id)
);

CREATE INDEX IF NOT EXISTS predictions_by_manager
    ON reporting_predictions (run_id, company_id, accepted_manager_id)
    WHERE accepted_manager_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS benchmark_truth (
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    manager_employee_id TEXT,
    canonical_title TEXT NOT NULL,
    canonical_department TEXT NOT NULL,
    canonical_team TEXT NOT NULL,
    canonical_level TEXT NOT NULL,
    is_people_manager INTEGER NOT NULL CHECK (is_people_manager IN (0, 1)),
    is_root INTEGER NOT NULL CHECK (is_root IN (0, 1)),
    PRIMARY KEY (company_id, employee_id),
    CHECK (manager_employee_id IS NULL OR manager_employee_id <> employee_id),
    CHECK ((is_root = 1 AND manager_employee_id IS NULL)
        OR (is_root = 0 AND manager_employee_id IS NOT NULL)),
    FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, employee_id),
    FOREIGN KEY (company_id, manager_employee_id) REFERENCES employees (company_id, employee_id)
);

CREATE TABLE IF NOT EXISTS prediction_reasons (
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    reason TEXT NOT NULL,
    PRIMARY KEY (run_id, company_id, employee_id, position),
    FOREIGN KEY (run_id, company_id, employee_id)
        REFERENCES reporting_predictions (run_id, company_id, employee_id)
);

CREATE TABLE IF NOT EXISTS employee_noise (
    company_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK (position >= 0),
    noise_type TEXT NOT NULL,
    PRIMARY KEY (company_id, employee_id, position),
    FOREIGN KEY (company_id, employee_id) REFERENCES employees (company_id, employee_id)
);

CREATE TABLE IF NOT EXISTS company_run_metrics (
    run_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    resolved_count INTEGER NOT NULL CHECK (resolved_count >= 0),
    unresolved_count INTEGER NOT NULL CHECK (unresolved_count >= 0),
    coverage REAL NOT NULL CHECK (coverage BETWEEN 0 AND 1),
    precision REAL NOT NULL CHECK (precision BETWEEN 0 AND 1),
    average_confidence REAL NOT NULL CHECK (average_confidence BETWEEN 0 AND 1),
    PRIMARY KEY (run_id, company_id),
    FOREIGN KEY (run_id) REFERENCES inference_runs (run_id),
    FOREIGN KEY (company_id) REFERENCES companies (company_id)
);

-- One inspectable decision per employee and run. The answer key is deliberately absent.
CREATE VIEW IF NOT EXISTS employee_reporting_audit AS
SELECT
    p.run_id, e.company_id, e.employee_id, e.full_name, e.job_title,
    e.raw_department, e.raw_team, e.location,
    f.inferred_department, f.inferred_level,
    p.accepted_manager_id, manager.full_name AS inferred_manager,
    p.best_candidate_id, candidate.full_name AS leading_candidate,
    p.confidence, p.margin, p.decision,
    r.probability_threshold, r.margin_threshold,
    CASE
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
