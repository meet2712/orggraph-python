-- Read-only checks for the current source rows and derived inference views.
-- Run with: sqlite3 -header -column instance/orggraph.sqlite3 < scripts/quality_checks.sql

pragma foreign_keys = on;
pragma foreign_key_check;

-- Only the two source tables should be persisted.
select type, name from sqlite_master
where type in ('table', 'view') and name not like 'sqlite_%'
order by type, name;

select 'companies' as object_name, count(*) as row_count from companies
union all select 'employees', count(*) from employees
union all select 'company_overview', count(*) from company_overview
union all select 'employee_reporting_decisions', count(*) from employee_reporting_decisions;

-- Expected: zero rows. Company count and size band are calculated from employees.
select c.company_id, c.employee_count, count(e.employee_id) as actual_count
from company_overview as c left join employees as e using (company_id)
group by c.company_id, c.employee_count
having c.employee_count <> count(e.employee_id);

-- Expected: zero rows. Every observed employee has exactly one decision.
select e.company_id, e.employee_id, count(p.employee_id) as prediction_rows
from employees as e left join employee_reporting_decisions as p using (company_id, employee_id)
group by e.company_id, e.employee_id
having count(p.employee_id) <> 1;

-- Expected: zero rows. Accepted edges must name the leading candidate and stay in company.
select p.company_id, p.employee_id, p.accepted_manager_id, p.best_candidate_id,
       p.confidence, p.margin, p.decision
from employee_reporting_decisions as p
left join employees as m on m.company_id = p.company_id
    and m.employee_id = p.accepted_manager_id
where p.confidence not between 0 and 1
   or p.margin not between 0 and p.confidence
   or p.accepted_manager_id = p.employee_id
   or p.best_candidate_id = p.employee_id
   or (p.decision = 'accepted' and (
       p.accepted_manager_id is null or p.accepted_manager_id <> p.best_candidate_id
       or m.employee_id is null))
   or (p.decision <> 'accepted' and p.accepted_manager_id is not null);

-- Expected: zero rows. Every accepted manager has a higher leadership rank.
select p.company_id, p.employee_id, p.accepted_manager_id
from employee_reporting_decisions as p
join employee_reporting_features as report using (company_id, employee_id)
join employee_reporting_features as manager on manager.company_id = p.company_id
    and manager.employee_id = p.accepted_manager_id
where manager.inferred_rank <= report.inferred_rank;

-- Expected: zero rows. Strictly higher rank should prevent cycles.
with recursive walk as (
    select company_id, employee_id as start_id, employee_id,
           accepted_manager_id, '|' || employee_id || '|' as path, 0 as cycle
    from employee_reporting_decisions where accepted_manager_id is not null
    union all
    select w.company_id, w.start_id, p.employee_id, p.accepted_manager_id,
           w.path || p.employee_id || '|',
           instr(w.path, '|' || p.employee_id || '|') > 0
    from walk as w join employee_reporting_decisions as p
      on p.company_id = w.company_id and p.employee_id = w.accepted_manager_id
    where w.cycle = 0
)
select company_id, start_id, path from walk where cycle = 1;

-- Source fields remain messy rather than being overwritten by display labels.
select sum(trim(job_title) = '') as missing_titles,
       sum(trim(location) = '') as missing_locations,
       sum(lower(trim(raw_department)) in ('', 'n/a', 'unknown', '-')) as missing_departments,
       sum(lower(trim(raw_team)) in ('', 'n/a', 'unknown', '-')) as missing_teams
from employees;

select decision, count(*) as employees from employee_reporting_decisions group by decision;

-- Expected: zero rows. The published acceptance thresholds come from the SQL view.
select p.company_id, p.employee_id from employee_reporting_decisions as p
cross join reporting_thresholds as s
where p.decision = 'accepted'
  and (p.confidence < s.score_threshold or p.margin < s.margin_threshold);

-- Example: inspect one employee's live manager chain.
with recursive manager_chain as (
    select company_id, employee_id, accepted_manager_id, 0 as depth
    from employee_reporting_decisions
    where company_id = 'cmp_0001' and employee_id = 'emp_0000178'
    union all
    select p.company_id, p.employee_id, p.accepted_manager_id, chain.depth + 1
    from manager_chain as chain join employee_reporting_decisions as p
      on p.company_id = chain.company_id and p.employee_id = chain.accepted_manager_id
    where chain.depth < 12
)
select chain.depth, e.full_name, e.job_title, m.full_name as inferred_manager
from manager_chain as chain
join employees as e using (company_id, employee_id)
left join employees as m on m.company_id = chain.company_id
    and m.employee_id = chain.accepted_manager_id
order by chain.depth;
