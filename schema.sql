PRAGMA foreign_keys = ON;

-- Only observed source records are stored. Every other object below is a
-- read-only view, recalculated when an employee is inserted or changed.
CREATE TABLE companies (
    company_id TEXT PRIMARY KEY,
    company_name TEXT NOT NULL,
    industry TEXT NOT NULL,
    headquarters TEXT NOT NULL
);

CREATE TABLE employees (
    company_id TEXT NOT NULL REFERENCES companies(company_id),
    employee_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    job_title TEXT NOT NULL,
    raw_department TEXT NOT NULL,
    raw_team TEXT NOT NULL,
    location TEXT NOT NULL,
    work_email TEXT NOT NULL,
    PRIMARY KEY (company_id, employee_id)
);

CREATE INDEX employees_by_company_team ON employees(company_id, raw_team);

-- Acceptance settings are one row, not a saved or historical run.
CREATE VIEW inference_settings AS
SELECT 0.98 AS score_threshold, 0.04 AS margin_threshold;

CREATE VIEW company_profiles AS
SELECT c.company_id, c.company_name, c.industry,
       CASE WHEN count(e.employee_id) < 130 THEN 'Small'
            WHEN count(e.employee_id) < 180 THEN 'Growth'
            ELSE 'Mid-market' END AS size_band,
       count(e.employee_id) AS employee_count, c.headquarters
FROM companies c LEFT JOIN employees e USING(company_id)
GROUP BY c.company_id;

-- Normalize only the observed text; no answer-key columns enter inference.
CREATE VIEW employee_text AS
SELECT e.company_id, e.employee_id, e.location,
       ' ' || trim(replace(replace(replace(replace(replace(replace(replace(
           replace(replace(replace(replace(lower(e.job_title),
             'manger', 'manager'), 'enginering', 'engineering'),
             'analtyics', 'analytics'), 'securty', 'security'),
           '.', ' '), ',', ' '), '-', ' '), '/', ' '),
           '  ', ' '), '  ', ' '), '  ', ' ')) || ' ' AS title_text,
       lower(trim(replace(replace(replace(e.raw_team, '  ', ' '),
           ' / ', '/'), ' /', '/'))) AS team_path,
       lower(trim(e.raw_department)) AS department_text
FROM employees e;

-- A title is a management signal only when it explicitly describes a
-- leadership role. Senior, Staff and Principal ICs remain individual
-- contributors. Manager in an account/product/success IC title is ambiguous.
CREATE VIEW employee_classification AS
SELECT t.company_id, t.employee_id, t.location, t.team_path,
       CASE
         WHEN title_text LIKE '% chief executive officer %' OR trim(title_text) = 'ceo'
           THEN 'CEO'
         WHEN title_text LIKE '% chief %'
           OR trim(title_text) IN ('cto','cro','coo','cpo','cmo','cdo','cfo','ciso','cio','cco')
           OR title_text LIKE ' cpo %'
           OR title_text LIKE '% general counsel %' THEN 'C-Suite'
         WHEN title_text LIKE '% vice president %' OR title_text LIKE '% vp %'
           OR title_text LIKE ' head %' THEN 'VP / Head'
         WHEN title_text LIKE '% senior director %' OR title_text LIKE '% sr director %'
           THEN 'Senior Director'
         WHEN title_text LIKE '% director %' THEN 'Director'
         WHEN title_text LIKE '% team lead %' OR title_text LIKE '% supervisor %'
           THEN 'Team Lead / Supervisor'
         WHEN (
           title_text LIKE '% product manager %' OR title_text LIKE '% product mgr %'
           OR title_text LIKE '% account manager %' OR title_text LIKE '% account mgr %'
           OR title_text LIKE '% customer success manager %'
           OR title_text LIKE '% customer success mgr %'
           OR title_text LIKE '% cust success manager %'
           OR title_text LIKE '% cust success mgr %'
         ) AND (
           title_text LIKE ' junior %' OR title_text LIKE ' jr %'
           OR title_text LIKE ' senior %' OR title_text LIKE ' sr %'
           OR title_text LIKE ' staff %' OR title_text LIKE ' principal %'
           OR trim(title_text) IN ('product manager','product mgr','account manager',
             'account mgr','customer success manager','customer success mgr',
             'cust success manager','cust success mgr')
           OR title_text LIKE ' account manager %'
           OR title_text LIKE ' account mgr %'
           OR title_text LIKE ' customer success manager %'
           OR title_text LIKE ' customer success mgr %'
           OR title_text LIKE ' cust success manager %'
           OR title_text LIKE ' cust success mgr %'
         )
           THEN CASE WHEN title_text LIKE ' junior %' OR title_text LIKE ' jr %'
                       THEN 'Junior IC'
                     WHEN title_text LIKE ' senior %' OR title_text LIKE ' sr %'
                       THEN 'Senior IC'
                     WHEN title_text LIKE ' staff %' OR title_text LIKE ' principal %'
                       THEN 'Principal / Staff IC'
                     ELSE 'Individual Contributor' END
         WHEN title_text LIKE '% senior % manager %'
           OR title_text LIKE '% sr % manager %'
           OR title_text LIKE '% senior % mgr %'
           OR title_text LIKE '% sr % mgr %'
           THEN 'Senior Manager'
         WHEN title_text LIKE '% manager %' OR title_text LIKE '% mgr %'
           OR title_text LIKE '% group product %'
           OR trim(title_text) = 'program lead' THEN 'Manager'
         WHEN title_text LIKE ' staff %' OR title_text LIKE ' principal %'
           OR title_text LIKE ' lead %' OR title_text LIKE '% lead '
           THEN 'Principal / Staff IC'
         WHEN title_text LIKE ' senior %' OR title_text LIKE ' sr %'
           THEN 'Senior IC'
         WHEN title_text LIKE ' junior %' OR title_text LIKE ' jr %'
           THEN 'Junior IC'
         ELSE 'Individual Contributor'
       END AS inferred_level,
       CASE
         WHEN title_text LIKE '% chief executive officer %' OR trim(title_text) = 'ceo'
           THEN 'Executive'
         WHEN title_text LIKE '% quality %' OR title_text LIKE '% qa %'
           THEN 'Engineering'
         WHEN title_text LIKE '% marketing %' OR title_text LIKE '% mktg %'
           OR title_text LIKE '% growth %' OR title_text LIKE '% demand gen %'
           THEN 'Marketing'
         WHEN title_text LIKE '% data %' OR title_text LIKE '% analytics %'
           OR title_text LIKE '% analyst %' OR title_text LIKE '% machine learning %'
           THEN 'Data & Analytics'
         WHEN title_text LIKE '% security %' OR title_text LIKE '% infosec %'
           THEN 'Security'
         WHEN title_text LIKE '% product engineering %' OR title_text LIKE '% product eng %'
           THEN 'Engineering'
         WHEN title_text LIKE '% product %' OR title_text LIKE '% ux %'
           OR title_text LIKE '% design %' THEN 'Product'
         WHEN title_text LIKE '% customer success %' OR title_text LIKE '% support %'
           OR title_text LIKE '% onboarding %' THEN 'Customer Success'
         WHEN title_text LIKE '% sales %' OR title_text LIKE '% revenue %'
           OR title_text LIKE '% account %' OR title_text LIKE '% partnership %'
           THEN 'Sales'
         WHEN title_text LIKE '% finance %' OR title_text LIKE '% financial %'
           OR title_text LIKE '% accounting %' OR title_text LIKE '% cfo %'
           THEN 'Finance'
         WHEN title_text LIKE '% people %' OR title_text LIKE '% human resources %'
           OR title_text LIKE '% hr %' OR title_text LIKE '% talent %'
           THEN 'People'
         WHEN title_text LIKE '% legal %' OR title_text LIKE '% counsel %'
           OR title_text LIKE '% compliance %' THEN 'Legal'
         WHEN title_text LIKE '% operations %' OR title_text LIKE '% ops %'
           OR title_text LIKE '% program %' THEN 'Operations'
         WHEN title_text LIKE '% information technology %' OR title_text LIKE '% it %'
           OR title_text LIKE '% infrastructure %' THEN 'IT'
         WHEN title_text LIKE '% engineer %' OR title_text LIKE '% engineering %'
           OR title_text LIKE '% developer %'
           OR title_text LIKE '% software %' OR title_text LIKE '% technology %'
           OR title_text LIKE '% eng %' OR title_text LIKE '% cto %'
           THEN 'Engineering'
         WHEN department_text IN ('eng','engineering','tech','software') THEN 'Engineering'
         WHEN department_text IN ('ops','operations','bizops') THEN 'Operations'
         WHEN department_text IN ('hr','people','people ops') THEN 'People'
         WHEN department_text IN ('mktg','marketing','growth') THEN 'Marketing'
         WHEN department_text IN ('sales','revenue','commercial') THEN 'Sales'
         WHEN department_text IN ('data','analytics','bi') THEN 'Data & Analytics'
         WHEN department_text IN ('cs','customer success','cx') THEN 'Customer Success'
         WHEN department_text IN ('fin','finance','accounting') THEN 'Finance'
         WHEN department_text IN ('prod','product') THEN 'Product'
         WHEN department_text IN ('security','infosec') THEN 'Security'
         WHEN department_text IN ('legal','compliance') THEN 'Legal'
         WHEN department_text IN ('it','information technology') THEN 'IT'
         ELSE 'Unclassified' END AS inferred_department
FROM employee_text t;

CREATE VIEW employee_features AS
SELECT company_id, employee_id, inferred_department,
       inferred_level,
       CASE inferred_level
         WHEN 'CEO' THEN 10 WHEN 'C-Suite' THEN 9
         WHEN 'VP / Head' THEN 8 WHEN 'Senior Director' THEN 7
         WHEN 'Director' THEN 6 WHEN 'Senior Manager' THEN 5
         WHEN 'Manager' THEN 4
         WHEN 'Team Lead / Supervisor' THEN 3
         WHEN 'Principal / Staff IC' THEN 3
         WHEN 'Senior IC' THEN 2 WHEN 'Junior IC' THEN 0
         ELSE 1 END AS inferred_rank
FROM employee_classification;

-- Candidate set stays inside one company and permits only explicit managers.
-- A management role may report to the next available higher layer. ICs can
-- report to an explicit Team Lead or Manager, but never to a Senior IC.
CREATE VIEW manager_candidates AS
SELECT r.company_id, r.employee_id, c.employee_id AS candidate_id,
       rf.inferred_rank AS report_rank, cf.inferred_rank AS candidate_rank,
       rf.inferred_level AS report_level, cf.inferred_level AS candidate_level,
       rf.inferred_department AS report_department,
       cf.inferred_department AS candidate_department,
       c.team_path AS candidate_team,
       CASE WHEN r.team_path = c.team_path AND r.team_path NOT IN ('','n/a','unknown','-')
                 THEN 'same_team'
            WHEN r.team_path <> '' AND c.team_path <> ''
                 AND r.team_path LIKE c.team_path || '/%'
                 THEN 'parent_team'
            ELSE 'other' END AS team_relation,
       CASE WHEN r.location <> '' AND r.location = c.location THEN 1 ELSE 0 END
         AS same_location
FROM employee_classification r
JOIN employee_features rf USING(company_id, employee_id)
JOIN employee_classification c ON c.company_id = r.company_id
JOIN employee_features cf ON cf.company_id = c.company_id AND cf.employee_id = c.employee_id
WHERE r.employee_id <> c.employee_id
  AND cf.inferred_level IN ('CEO','C-Suite','VP / Head','Senior Director',
        'Director','Senior Manager','Manager','Team Lead / Supervisor')
  AND (
      (rf.inferred_rank < 3 AND cf.inferred_rank >= 3)
      OR (rf.inferred_level IN ('Senior IC','Principal / Staff IC')
          AND cf.inferred_rank >= 4)
      OR (rf.inferred_level = 'Team Lead / Supervisor' AND cf.inferred_rank >= 4)
      OR (rf.inferred_rank >= 4 AND cf.inferred_rank > rf.inferred_rank)
  )
  AND (
      r.team_path = c.team_path
      OR r.team_path LIKE c.team_path || '/%'
      OR cf.inferred_level = 'CEO'
  );

-- Scores represent strength of visible hierarchy evidence, not a learned
-- probability. Missing or conflicting team paths fall below the accept floor.
CREATE VIEW candidate_scores AS
SELECT m.company_id, m.employee_id, m.candidate_id,
       m.candidate_rank, m.candidate_team,
       CASE
         WHEN report_level = 'C-Suite' AND candidate_level = 'CEO' THEN 0.995
         WHEN report_level = 'VP / Head' AND candidate_level = 'CEO'
              AND team_relation = 'parent_team' THEN 0.94
         WHEN report_level = 'VP / Head' AND candidate_level = 'C-Suite'
              AND team_relation = 'parent_team' THEN 0.99
         WHEN report_level IN ('Junior IC','Individual Contributor')
              AND candidate_level = 'Team Lead / Supervisor'
              AND team_relation = 'same_team' THEN 0.995
         WHEN report_level IN ('Senior IC','Principal / Staff IC')
              AND candidate_level = 'Manager'
              AND team_relation = 'same_team' THEN 0.99
         WHEN report_level = 'Team Lead / Supervisor'
              AND candidate_level = 'Manager'
              AND team_relation = 'same_team' THEN 0.995
         -- A same-team manager is strong evidence for an IC when the function
         -- has no observed team lead who could be the closer manager.
         WHEN report_level IN ('Junior IC','Individual Contributor')
              AND candidate_level = 'Manager'
              AND team_relation = 'same_team'
              AND report_department = candidate_department
              AND report_department <> 'Unclassified'
              AND NOT EXISTS (
                  SELECT 1 FROM employee_features lead
                  WHERE lead.company_id = m.company_id
                    AND lead.inferred_department = m.report_department
                    AND lead.inferred_level = 'Team Lead / Supervisor'
              ) THEN 0.99
         -- Skip a hierarchy layer only when it is absent in this function.
         WHEN report_level = 'Director' AND candidate_level = 'VP / Head'
              AND report_department = candidate_department
              AND report_department <> 'Unclassified'
              AND team_relation IN ('same_team','parent_team') THEN 0.99
         WHEN report_level = 'Manager' AND candidate_level = 'Director'
              AND report_department = candidate_department
              AND report_department <> 'Unclassified'
              AND team_relation IN ('same_team','parent_team')
              AND NOT EXISTS (
                  SELECT 1 FROM employee_features intermediate
                  WHERE intermediate.company_id = m.company_id
                    AND intermediate.inferred_department = m.report_department
                    AND intermediate.inferred_level = 'Senior Manager'
              ) THEN 0.99
         WHEN report_level = 'Manager' AND candidate_level = 'VP / Head'
              AND report_department = candidate_department
              AND report_department <> 'Unclassified'
              AND team_relation IN ('same_team','parent_team')
              AND NOT EXISTS (
                  SELECT 1 FROM employee_features intermediate
                  WHERE intermediate.company_id = m.company_id
                    AND intermediate.inferred_department = m.report_department
                    AND intermediate.inferred_level IN ('Director','Senior Manager')
              ) THEN 0.99
         WHEN report_rank < 4 AND candidate_level = 'Manager'
              AND team_relation = 'same_team' THEN 0.95
         WHEN report_rank >= 4 AND candidate_rank = report_rank + 1
              AND team_relation IN ('same_team','parent_team') THEN 0.99
         WHEN report_rank >= 4 AND candidate_rank = report_rank + 2
              AND team_relation IN ('same_team','parent_team') THEN 0.94
         WHEN report_rank >= 4 AND candidate_rank > report_rank
              AND team_relation = 'parent_team'
              THEN 0.90 - 0.02 * (candidate_rank - report_rank - 3)
         WHEN report_rank < 4 AND candidate_level = 'Manager'
              AND team_relation = 'parent_team' THEN 0.75
         WHEN report_department = candidate_department
              AND report_department <> 'Unclassified' THEN 0.67
         WHEN candidate_level = 'CEO' THEN 0.45
         ELSE 0.20 END
         + CASE WHEN same_location = 1 THEN 0.002 ELSE 0 END
         AS evidence_score
FROM manager_candidates m;

-- Correlate the shortlist to one employee so a company-page lookup does not
-- rank every employee in the database. JSON is only an internal way to fetch
-- the top two in one scan; the view exposes named candidate and score columns.
CREATE VIEW employee_top_candidates AS
SELECT e.company_id, e.employee_id,
       json_extract(shortlist.value, '$[0][0]') AS best_candidate_id,
       json_extract(shortlist.value, '$[0][1]') AS best_score,
       json_extract(shortlist.value, '$[1][1]') AS second_score
FROM employees e
CROSS JOIN json_each(json_array(
    (SELECT json_group_array(json_array(top.candidate_id, top.evidence_score))
     FROM (
         SELECT s.candidate_id, s.evidence_score
         FROM candidate_scores s
         WHERE s.company_id = e.company_id AND s.employee_id = e.employee_id
         ORDER BY s.evidence_score DESC, length(s.candidate_team) DESC,
                  s.candidate_rank ASC, s.candidate_id
         LIMIT 2
     ) top)
)) AS shortlist;

CREATE VIEW reporting_predictions AS
WITH scored AS (
    SELECT e.company_id, e.employee_id, f.inferred_level,
           t.best_candidate_id AS candidate_id,
           round(coalesce(t.best_score, 0.0), 4) AS confidence,
           round(max(0.0, coalesce(t.best_score, 0.0) -
                    coalesce(t.second_score, 0.0)), 4) AS margin
    FROM employees e
    JOIN employee_features f USING(company_id, employee_id)
    JOIN employee_top_candidates t USING(company_id, employee_id)
)
SELECT company_id, employee_id,
       CASE WHEN inferred_level <> 'CEO' AND confidence >= s.score_threshold
                  AND margin >= s.margin_threshold THEN candidate_id END AS accepted_manager_id,
       candidate_id AS best_candidate_id,
       min(1.0, confidence) AS confidence, margin,
       CASE WHEN inferred_level = 'CEO' THEN 'company_root'
            WHEN confidence >= s.score_threshold AND margin >= s.margin_threshold THEN 'accepted'
            ELSE 'unresolved' END AS decision
FROM scored CROSS JOIN inference_settings s;

CREATE VIEW prediction_reasons AS
SELECT p.company_id, p.employee_id,
       CASE WHEN p.decision = 'company_root' THEN 'CEO is the company root'
            WHEN p.best_candidate_id IS NULL THEN 'No suitable management title'
            WHEN p.decision = 'accepted' THEN 'Team path and seniority identify a manager'
            WHEN p.confidence < s.score_threshold THEN 'Insufficient team or role evidence'
            ELSE 'Several candidates have similar evidence' END AS reason
FROM reporting_predictions p CROSS JOIN inference_settings s;

CREATE VIEW company_metrics AS
SELECT p.company_id,
       sum(p.decision = 'accepted') AS resolved_count,
       sum(p.decision = 'unresolved') AS unresolved_count,
       round(1.0 * sum(p.decision = 'accepted') /
             max(sum(p.decision <> 'company_root'), 1), 4) AS coverage,
       round(coalesce(avg(CASE WHEN p.decision = 'accepted'
             THEN p.confidence END), 0), 4) AS average_confidence
FROM reporting_predictions p GROUP BY p.company_id;

CREATE VIEW dataset_metrics AS
SELECT count(DISTINCT company_id) AS company_count,
       count(*) AS employee_count,
       sum(decision = 'accepted') AS accepted_count,
       sum(decision = 'unresolved') AS unresolved_count,
       round(coalesce(avg(CASE WHEN decision = 'accepted'
             THEN confidence END), 0), 4) AS average_resolved_confidence
FROM reporting_predictions;

CREATE VIEW employee_reporting_audit AS
SELECT e.company_id, e.employee_id, e.full_name, e.job_title,
       e.raw_department, e.raw_team, e.location,
       f.inferred_department, f.inferred_level,
       p.accepted_manager_id, manager.full_name AS inferred_manager,
       p.best_candidate_id, candidate.full_name AS leading_candidate,
       p.confidence, p.margin, p.decision,
       s.score_threshold, s.margin_threshold,
       CASE WHEN p.decision = 'company_root' THEN 'observed_ceo_title'
            WHEN p.decision = 'accepted' THEN 'cleared_both_checks'
            WHEN p.best_candidate_id IS NULL THEN 'no_suitable_candidate'
            WHEN p.confidence < s.score_threshold THEN 'low_confidence'
            ELSE 'ambiguous_candidates' END AS decision_reason
FROM reporting_predictions p
JOIN employees e USING(company_id, employee_id)
JOIN employee_features f USING(company_id, employee_id)
CROSS JOIN inference_settings s
LEFT JOIN employees manager ON manager.company_id = p.company_id
      AND manager.employee_id = p.accepted_manager_id
LEFT JOIN employees candidate ON candidate.company_id = p.company_id
      AND candidate.employee_id = p.best_candidate_id;
