-- Company-scoped version of reporting_predictions. The MATERIALIZED CTE
-- classifies each employee once, which keeps site pages fast while every
-- decision remains a live SQL calculation from the two source tables.
WITH scoped AS MATERIALIZED (
    SELECT c.*, f.inferred_rank, t.title_text
    FROM employee_classification c
    JOIN employee_features f USING(company_id, employee_id)
    JOIN employee_text t USING(company_id, employee_id)
    WHERE c.company_id = :company_id
),
pairs AS MATERIALIZED (
    SELECT r.company_id, r.employee_id, c.employee_id AS candidate_id,
           r.inferred_rank AS report_rank, c.inferred_rank AS candidate_rank,
           r.inferred_level AS report_level, c.inferred_level AS candidate_level,
           r.inferred_department AS report_department,
           c.inferred_department AS candidate_department,
           r.team_path AS report_team, c.team_path AS candidate_team,
           r.title_text AS report_title, c.title_text AS candidate_title,
           CASE WHEN r.team_path = c.team_path
                     AND r.team_path NOT IN ('','n/a','unknown','-')
                     THEN 'same_team'
                WHEN r.team_path NOT IN ('','n/a','unknown','-')
                     AND c.team_path NOT IN ('','n/a','unknown','-')
                     AND substr(r.team_path, 1, length(c.team_path) + 1) = c.team_path || '/'
                     THEN 'parent_team'
                ELSE 'other' END AS team_relation,
           CASE WHEN r.location <> '' AND r.location = c.location THEN 1 ELSE 0 END
             AS same_location
    FROM scoped r JOIN scoped c ON r.employee_id <> c.employee_id
    WHERE c.inferred_level IN ('CEO','C-Suite','VP / Head','Senior Director',
          'Director','Senior Manager','Manager','Team Lead / Supervisor')
      AND (
          (r.inferred_rank < 3 AND c.inferred_rank >= 3)
          OR (r.inferred_level IN ('Senior IC','Principal / Staff IC')
              AND c.inferred_rank >= 4)
          OR (r.inferred_level = 'Team Lead / Supervisor' AND c.inferred_rank >= 4)
          OR (r.inferred_rank >= 4 AND c.inferred_rank > r.inferred_rank)
      )
      AND ((r.team_path = c.team_path AND r.team_path NOT IN ('','n/a','unknown','-'))
           OR (c.team_path NOT IN ('','n/a','unknown','-') AND substr(r.team_path, 1, length(c.team_path) + 1) = c.team_path || '/')
           OR c.inferred_level = 'CEO'
           OR (r.team_path IN ('','n/a','unknown','-')
               AND r.inferred_level IN ('Junior IC','Individual Contributor','Senior IC','Principal / Staff IC')
               AND c.inferred_level IN ('Manager','Team Lead / Supervisor')
               AND r.inferred_department = c.inferred_department
               AND r.inferred_department <> 'Unclassified'
               AND ((r.title_text LIKE '% qa %' AND c.title_text LIKE '% qa %')
                 OR (r.title_text LIKE '% security %' AND c.title_text LIKE '% security %'))))
),
scored AS MATERIALIZED (
    SELECT p.*,
           CASE
             WHEN report_level IN ('Junior IC','Individual Contributor','Senior IC','Principal / Staff IC')
                  AND candidate_level IN ('Manager','Team Lead / Supervisor')
                  AND team_relation = 'other'
                  AND report_team IN ('','n/a','unknown','-')
                  AND report_department = candidate_department
                  AND report_department <> 'Unclassified'
                  AND ((report_title LIKE '% qa %' AND candidate_title LIKE '% qa %')
                    OR (report_title LIKE '% security %' AND candidate_title LIKE '% security %'))
                  AND NOT EXISTS (
                      SELECT 1 FROM scoped other
                      WHERE other.employee_id <> p.candidate_id
                        AND other.inferred_level IN ('Manager','Team Lead / Supervisor')
                        AND other.inferred_department = p.report_department
                        AND ((p.report_title LIKE '% qa %' AND other.title_text LIKE '% qa %')
                          OR (p.report_title LIKE '% security %' AND other.title_text LIKE '% security %'))
                  ) THEN 0.99
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
             WHEN report_level IN ('Junior IC','Individual Contributor')
                  AND candidate_level = 'Manager'
                  AND team_relation = 'same_team'
                  AND report_department = candidate_department
                  AND report_department <> 'Unclassified'
                  AND NOT EXISTS (
                      SELECT 1 FROM scoped lead
                      WHERE lead.inferred_department = p.report_department
                        AND lead.inferred_level = 'Team Lead / Supervisor'
                  ) THEN 0.99
             WHEN report_level = 'Director' AND candidate_level = 'VP / Head'
                  AND report_department = candidate_department
                  AND report_department <> 'Unclassified'
                  AND team_relation IN ('same_team','parent_team') THEN 0.99
             WHEN report_level = 'Manager' AND candidate_level = 'Director'
                  AND report_department = candidate_department
                  AND report_department <> 'Unclassified'
                  AND team_relation IN ('same_team','parent_team')
                  AND NOT EXISTS (
                      SELECT 1 FROM scoped intermediate
                      WHERE intermediate.inferred_department = p.report_department
                        AND intermediate.inferred_level = 'Senior Manager'
                  ) THEN 0.99
             WHEN report_level = 'Manager' AND candidate_level = 'VP / Head'
                  AND report_department = candidate_department
                  AND report_department <> 'Unclassified'
                  AND team_relation IN ('same_team','parent_team')
                  AND NOT EXISTS (
                      SELECT 1 FROM scoped intermediate
                      WHERE intermediate.inferred_department = p.report_department
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
             + CASE WHEN same_location = 1 THEN 0.002 ELSE 0 END AS evidence_score
    FROM pairs p
),
ranked AS (
    SELECT s.*,
           row_number() OVER (
               PARTITION BY company_id, employee_id
               ORDER BY evidence_score DESC, length(candidate_team) DESC,
                        candidate_rank ASC, candidate_id
           ) AS candidate_position
    FROM scored s
),
finalists AS (
    SELECT company_id, employee_id,
           max(CASE WHEN candidate_position = 1 THEN candidate_id END) AS candidate_id,
           max(CASE WHEN candidate_position = 1 THEN evidence_score END) AS top_score,
           max(CASE WHEN candidate_position = 2 THEN evidence_score END) AS runner_up_score
    FROM ranked WHERE candidate_position <= 2
    GROUP BY company_id, employee_id
),
decision AS (
    SELECT r.company_id, r.employee_id, r.inferred_level,
           finalists.candidate_id,
           round(coalesce(finalists.top_score, 0.0), 4) AS confidence,
           round(max(0.0, coalesce(finalists.top_score, 0.0) -
                    coalesce(finalists.runner_up_score, 0.0)), 4) AS margin
    FROM scoped r LEFT JOIN finalists USING(company_id, employee_id)
)
SELECT company_id, employee_id,
       CASE WHEN inferred_level <> 'CEO' AND confidence >= settings.score_threshold
                  AND margin >= settings.margin_threshold THEN candidate_id END AS accepted_manager_id,
       candidate_id AS best_candidate_id,
       min(1.0, confidence) AS confidence, margin,
       CASE WHEN inferred_level = 'CEO' THEN 'company_root'
            WHEN confidence >= settings.score_threshold
                 AND margin >= settings.margin_threshold THEN 'accepted'
            ELSE 'unresolved' END AS decision
FROM decision CROSS JOIN inference_settings settings;
