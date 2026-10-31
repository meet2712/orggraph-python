-- Generated from schema.sql by scripts/build_company_query.py.
-- Scope the source rows first; all decision rules stay in the views.
with employees as materialized (
    select * from main.employees where company_id = :company_id
),
employee_role_classification as materialized (
with text as materialized (
    select e.company_id, e.employee_id, e.location,
           ' ' || trim(replace(replace(replace(replace(replace(replace(replace(
               replace(replace(replace(replace(lower(e.job_title),
                 'manger', 'manager'), 'enginering', 'engineering'),
                 'analtyics', 'analytics'), 'securty', 'security'),
               '.', ' '), ',', ' '), '-', ' '), '/', ' '),
               '  ', ' '), '  ', ' '), '  ', ' ')) || ' ' as title_text,
           lower(trim(replace(replace(replace(e.raw_team, '  ', ' '),
               ' / ', '/'), ' /', '/'))) as team_path,
           lower(trim(e.raw_department)) as department_text
    from employees e
)
select t.company_id, t.employee_id, t.location, t.team_path, t.title_text,
       case
         when title_text like '% chief executive officer %' or trim(title_text) = 'ceo'
           then 'CEO'
         when title_text like '% chief %'
           or trim(title_text) in ('cto','cro','coo','cpo','cmo','cdo','cfo','ciso','cio','cco')
           or title_text like ' cpo %'
           or title_text like '% general counsel %' then 'C-Suite'
         when title_text like '% vice president %' or title_text like '% vp %'
           or title_text like ' head %' then 'VP / Head'
         when title_text like '% senior director %' or title_text like '% sr director %'
           then 'Senior Director'
         when title_text like '% director %' then 'Director'
         when title_text like '% team lead %' or title_text like '% supervisor %'
           then 'Team Lead / Supervisor'
         when (
           title_text like '% product manager %' or title_text like '% product mgr %'
           or title_text like '% account manager %' or title_text like '% account mgr %'
           or title_text like '% customer success manager %'
           or title_text like '% customer success mgr %'
           or title_text like '% cust success manager %'
           or title_text like '% cust success mgr %'
         ) and (
           title_text like ' junior %' or title_text like ' jr %'
           or title_text like ' senior %' or title_text like ' sr %'
           or title_text like ' staff %' or title_text like ' principal %'
           or trim(title_text) in ('product manager','product mgr','account manager',
             'account mgr','customer success manager','customer success mgr',
             'cust success manager','cust success mgr')
           or title_text like ' account manager %'
           or title_text like ' account mgr %'
           or title_text like ' customer success manager %'
           or title_text like ' customer success mgr %'
           or title_text like ' cust success manager %'
           or title_text like ' cust success mgr %'
         )
           then case when title_text like ' junior %' or title_text like ' jr %'
                       then 'Junior IC'
                     when title_text like ' senior %' or title_text like ' sr %'
                       then 'Senior IC'
                     when title_text like ' staff %' or title_text like ' principal %'
                       then 'Principal / Staff IC'
                     else 'Individual Contributor' end
         when title_text like '% senior % manager %'
           or title_text like '% sr % manager %'
           or title_text like '% senior % mgr %'
           or title_text like '% sr % mgr %'
           then 'Senior Manager'
         when title_text like '% manager %' or title_text like '% mgr %'
           or title_text like '% group product %'
           or trim(title_text) = 'program lead' then 'Manager'
         when title_text like ' staff %' or title_text like ' principal %'
           or title_text like ' lead %' or title_text like '% lead '
           then 'Principal / Staff IC'
         when title_text like ' senior %' or title_text like ' sr %'
           then 'Senior IC'
         when title_text like ' junior %' or title_text like ' jr %'
           then 'Junior IC'
         else 'Individual Contributor'
       end as inferred_level,
       case
         when title_text like '% chief executive officer %' or trim(title_text) = 'ceo'
           then 'Executive'
         when title_text like '% quality %' or title_text like '% qa %'
           then 'Engineering'
         when title_text like '% marketing %' or title_text like '% mktg %'
           or title_text like '% growth %' or title_text like '% demand gen %'
           or title_text like '% demand generation %'
           then 'Marketing'
         when title_text like '% security %' or title_text like '% infosec %'
           then 'Security'
         when title_text like '% product engineering %' or title_text like '% product eng %'
           then 'Engineering'
         when title_text like '% product %' or title_text like '% ux %'
           or title_text like '% design %' then 'Product'
         when title_text like '% customer success %' or title_text like '% cust success %'
           or title_text like '% support %'
           or title_text like '% onboarding %' then 'Customer Success'
         when title_text like '% people %' or title_text like '% human resources %'
           or title_text like '% hr %' or title_text like '% talent %'
           then 'People'
         when title_text like '% operations %' or title_text like '% ops %'
           or title_text like '% program %' then 'Operations'
         when title_text like '% sales %' or title_text like '% revenue %'
           or title_text like '% account %' or title_text like '% partnership %'
           or title_text like '% partnerships %' or title_text like '% business development %'
           then 'Sales'
         when title_text like '% finance %' or title_text like '% financial %'
           or title_text like '% accounting %' or title_text like '% cfo %'
           or title_text like '% fp&a %'
           then 'Finance'
         when title_text like '% legal %' or title_text like '% counsel %'
           or title_text like '% compliance %' then 'Legal'
         when title_text like '% data %' or title_text like '% analytics %'
           or title_text like '% analyst %' or title_text like '% machine learning %'
           or title_text like '% bi %' then 'Data & Analytics'
         when title_text like '% information technology %' or title_text like '% it %'
           or title_text like '% infrastructure %' or title_text like '% network %'
           or title_text like '% systems administrator %' or title_text like '% helpdesk %'
           or title_text like '% help desk %' then 'IT'
         when title_text like '% engineer %' or title_text like '% engineering %'
           or title_text like '% developer %'
           or title_text like '% software %' or title_text like '% technology %'
           or title_text like '% eng %' or title_text like '% cto %'
           then 'Engineering'
         when department_text in ('eng','engineering','tech','software') then 'Engineering'
         when department_text in ('ops','operations','bizops') then 'Operations'
         when department_text in ('hr','people','people ops') then 'People'
         when department_text in ('mktg','marketing','growth') then 'Marketing'
         when department_text in ('sales','revenue','commercial') then 'Sales'
         when department_text in ('data','analytics','bi') then 'Data & Analytics'
         when department_text in ('cs','customer success','cx') then 'Customer Success'
         when department_text in ('fin','finance','accounting') then 'Finance'
         when department_text in ('prod','product') then 'Product'
         when department_text in ('security','infosec') then 'Security'
         when department_text in ('legal','compliance') then 'Legal'
         when department_text in ('it','information technology') then 'IT'
         else 'Unclassified' end as inferred_department
from text t
),
employee_reporting_features as materialized (
with classified as materialized (select * from employee_role_classification),
     role_profiles as materialized (
    select c.*,
           case
             when title_text like '% qa %' or title_text like '% quality %' then 'quality'
             when title_text like '% security %' or title_text like '% infosec %' then 'security'
             when title_text like '% data engineer %' or title_text like '% data engineering %'
               or title_text like '% data eng %' then 'data_engineering'
             when (title_text like '% analytics %' or title_text like '% bi %'
               or title_text like '% data analyst %')
               and c.inferred_level <> 'Team Lead / Supervisor' then 'analytics'
             when title_text like '% infrastructure %' or title_text like '% network %'
               or title_text like '% systems administrator %' then 'it_infrastructure'
             when title_text like '% fp&a %' or title_text like '% financial analyst %'
               or title_text like '% finance team lead %' then 'financial_planning'
             when title_text like '% business development %' then 'business_development'
             when title_text like '% demand generation %' or title_text like '% demand gen %'
               then 'demand_generation'
             when title_text like '% growth %' then 'growth_marketing'
             when title_text like '% business operations %' or title_text like '% business ops %'
               or title_text like '% operations analyst %' then 'business_operations'
             when title_text like '% people operations %' or title_text like '% people ops %'
               or title_text like '% people partner %' or title_text like '% hr coordinator %'
               then 'people_operations'
             when title_text like '% commercial legal %' or title_text like '% legal counsel %'
               or title_text like '% contracts specialist %' then 'commercial_legal'
             when title_text like '% program %' then 'programs'
             when c.inferred_department = 'Sales' then
               case
                 when title_text like '% mid market %' or c.team_path like '%/mid-market'
                   then 'sales_mid_market'
                 when title_text like '% enterprise %' or c.team_path like '%/enterprise'
                   then 'sales_enterprise'
                 when title_text like '% smb %' or c.team_path like '%/smb' then 'sales_smb'
                 else '' end
             -- Generic lead titles need a compatible observed team to identify
             -- their specialty; a misplaced team in another function is ignored.
             when c.inferred_level = 'Team Lead / Supervisor' then
               case
                 when c.inferred_department = 'Data & Analytics' and c.team_path like '%/data platform'
                   then 'data_engineering'
                 when c.inferred_department = 'Data & Analytics' and c.team_path like '%/analytics'
                   then 'analytics'
                 when c.inferred_department = 'Marketing' and c.team_path like '%/growth'
                   then 'growth_marketing'
                 when c.inferred_department = 'Marketing' and c.team_path like '%/demand generation'
                   then 'demand_generation'
                 when c.inferred_department = 'Operations' and c.team_path like '%/business operations'
                   then 'business_operations'
                 when c.inferred_department = 'IT' and c.team_path like '%/infrastructure'
                   then 'it_infrastructure'
                 when c.inferred_department = 'Sales' and c.team_path like '%/partnerships'
                   then 'business_development'
                 else '' end
             else '' end as role_family,
           case
             when title_text like '% chief technology %' or trim(title_text) in ('cto','cio','cdo','ciso')
               or title_text like '% chief product %' then 'Technology'
             when title_text like '% chief revenue %' or trim(title_text) in ('cro','cmo') then 'Revenue'
             when title_text like '% chief operating %' or trim(title_text) = 'coo' then 'Operations'
             when title_text like '% chief financial %' or trim(title_text) = 'cfo' then 'Finance & Risk'
             when title_text like '% chief people %' or title_text like ' cpo people %' then 'People'
             when c.inferred_level = 'C-Suite' then ''
             when c.inferred_department in ('Engineering','Product','Data & Analytics','Security','IT')
               then 'Technology'
             when c.inferred_department in ('Sales','Marketing','Customer Success') then 'Revenue'
             when c.inferred_department in ('Finance','Legal') then 'Finance & Risk'
             when c.inferred_department in ('People','Operations') then c.inferred_department
             else '' end as executive_portfolio
    from classified c
)
select p.*,
       case inferred_level
         when 'CEO' then 10 when 'C-Suite' then 9
         when 'VP / Head' then 8 when 'Senior Director' then 7
         when 'Director' then 6 when 'Senior Manager' then 5
         when 'Manager' then 4
         when 'Team Lead / Supervisor' then 3
         when 'Principal / Staff IC' then 3
         when 'Senior IC' then 2 when 'Junior IC' then 0
         else 1 end as inferred_rank
from role_profiles p
),
employee_manager_candidates as materialized (
with features as materialized (select * from employee_reporting_features)
select r.company_id, r.employee_id, c.employee_id as candidate_id,
       r.inferred_rank as report_rank, c.inferred_rank as candidate_rank,
       r.inferred_level as report_level, c.inferred_level as candidate_level,
       r.inferred_department as report_department,
       c.inferred_department as candidate_department,
       r.team_path as report_team, c.team_path as candidate_team,
       r.role_family as report_family, c.role_family as candidate_family,
       r.executive_portfolio as report_portfolio, c.executive_portfolio as candidate_portfolio,
       case when r.team_path = c.team_path and r.team_path not in ('','n/a','unknown','-')
                 then 'same_team'
            when r.team_path not in ('','n/a','unknown','-')
                 and c.team_path not in ('','n/a','unknown','-')
                 and substr(r.team_path, 1, length(c.team_path) + 1) = c.team_path || '/'
                 then 'parent_team'
            else 'other' end as team_relation,
       case when r.location <> '' and r.location = c.location then 1 else 0 end
         as same_location
from features r
join features c on c.company_id = r.company_id
where r.employee_id <> c.employee_id
  and c.inferred_level in ('CEO','C-Suite','VP / Head','Senior Director',
        'Director','Senior Manager','Manager','Team Lead / Supervisor')
  and (
      (r.inferred_level in ('Junior IC','Individual Contributor') and c.inferred_rank >= 3)
      or (r.inferred_level in ('Senior IC','Principal / Staff IC')
          and c.inferred_rank >= 4)
      or (r.inferred_level = 'Team Lead / Supervisor' and c.inferred_rank >= 4)
      or (r.inferred_rank >= 4 and c.inferred_rank > r.inferred_rank)
  )
  and (
      (r.team_path = c.team_path and r.team_path not in ('','n/a','unknown','-'))
      or (c.team_path not in ('','n/a','unknown','-') and substr(r.team_path, 1, length(c.team_path) + 1) = c.team_path || '/')
      or c.inferred_level = 'CEO'
      or (r.inferred_level = 'VP / Head' and c.inferred_level = 'C-Suite'
          and r.executive_portfolio <> ''
          and r.executive_portfolio = c.executive_portfolio)
      or ((r.team_path in ('','n/a','unknown','-') or c.team_path in ('','n/a','unknown','-'))
          and r.inferred_level in ('Junior IC','Individual Contributor','Senior IC','Principal / Staff IC')
          and c.inferred_level in ('Manager','Team Lead / Supervisor')
          and r.role_family <> '' and r.role_family = c.role_family)
  )
),
employee_manager_scores as materialized (
with features as materialized (select * from employee_reporting_features)
select m.company_id, m.employee_id, m.candidate_id,
       m.candidate_rank, m.candidate_team,
       case
         -- Match a specialist when a team is missing or the manager owns a
         -- parent team. The runner-up check rejects equally plausible matches.
         when report_family <> '' and report_family = candidate_family
              and report_level in ('Junior IC','Individual Contributor','Senior IC','Principal / Staff IC')
              and candidate_level in ('Manager','Team Lead / Supervisor')
              and (report_team in ('','n/a','unknown','-') or candidate_team in ('','n/a','unknown','-')
                   or team_relation = 'parent_team')
              -- A broad Staff/Principal title may belong to the whole function.
              and not (report_level = 'Principal / Staff IC'
                       and report_family in ('financial_planning','people_operations','business_operations'))
              and (candidate_level = 'Team Lead / Supervisor'
                   or report_level in ('Senior IC','Principal / Staff IC')
                   or not exists (
                       select 1 from features lead
                       where lead.company_id = m.company_id
                         and lead.inferred_department = m.report_department
                         and lead.inferred_level = 'Team Lead / Supervisor'
                         and (lead.role_family = m.report_family or lead.role_family = '')
                   ))
              and (candidate_level = 'Manager' or (
                  select count(*) from features manager
                  where manager.company_id = m.company_id
                    and manager.role_family = m.report_family
                    and manager.inferred_level = 'Manager'
              ) <= 1) then 0.995
         when report_level = 'VP / Head' and candidate_level = 'C-Suite'
              and report_portfolio <> '' and report_portfolio = candidate_portfolio
              then 0.99
         when report_level = 'VP / Head' and candidate_level = 'CEO'
              and team_relation = 'parent_team' and report_portfolio <> ''
              and not exists (
                  select 1 from features executive
                  where executive.company_id = m.company_id
                    and executive.inferred_level = 'C-Suite'
                    and (executive.executive_portfolio = m.report_portfolio
                         or executive.executive_portfolio = '')
              )
              and not exists (
                  select 1 from employees unknown
                  join features ut using(company_id, employee_id)
                  where unknown.company_id = m.company_id and trim(unknown.job_title) = ''
                    and ut.team_path not in ('','n/a','unknown','-','company')
                    and substr(m.report_team, 1, length(ut.team_path) + 1) = ut.team_path || '/'
              ) then 0.99
         when report_level = 'C-Suite' and candidate_level = 'CEO' then 0.995
         when report_level = 'VP / Head' and candidate_level = 'CEO'
              and team_relation = 'parent_team' then 0.94
         when report_level = 'VP / Head' and candidate_level = 'C-Suite'
              and team_relation = 'parent_team' then 0.99
         when report_level in ('Junior IC','Individual Contributor')
              and candidate_level = 'Team Lead / Supervisor'
              and team_relation = 'same_team' then 0.995
         when report_level in ('Senior IC','Principal / Staff IC')
              and candidate_level = 'Manager'
              and team_relation = 'same_team' then 0.99
         when report_level = 'Team Lead / Supervisor'
              and candidate_level = 'Manager'
              and team_relation = 'same_team' then 0.995
         -- A same-team manager is strong evidence for an IC when the function
         -- has no observed team lead who could be the closer manager.
         when report_level in ('Junior IC','Individual Contributor')
              and candidate_level = 'Manager'
              and team_relation = 'same_team'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and not exists (
                  select 1 from features lead
                  where lead.company_id = m.company_id
                    and lead.inferred_department = m.report_department
                    and lead.inferred_level = 'Team Lead / Supervisor'
              ) then 0.99
         -- Skip a hierarchy layer only when it is absent in this function.
         when report_level = 'Director' and candidate_level = 'VP / Head'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team') then 0.99
         when report_level = 'Manager' and candidate_level = 'Director'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team')
              and not exists (
                  select 1 from features intermediate
                  where intermediate.company_id = m.company_id
                    and intermediate.inferred_department = m.report_department
                    and intermediate.inferred_level = 'Senior Manager'
              ) then 0.99
         when report_level = 'Manager' and candidate_level = 'VP / Head'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team')
              and not exists (
                  select 1 from features intermediate
                  where intermediate.company_id = m.company_id
                    and intermediate.inferred_department = m.report_department
                    and intermediate.inferred_level in ('Director','Senior Manager')
              ) then 0.99
         when report_rank < 4 and candidate_level = 'Manager'
              and team_relation = 'same_team' then 0.95
         when report_rank >= 4 and candidate_rank = report_rank + 1
              and team_relation in ('same_team','parent_team') then 0.99
         when report_rank >= 4 and candidate_rank = report_rank + 2
              and team_relation in ('same_team','parent_team') then 0.94
         when report_rank >= 4 and candidate_rank > report_rank
              and team_relation = 'parent_team'
              then 0.90 - 0.02 * (candidate_rank - report_rank - 3)
         when report_rank < 4 and candidate_level = 'Manager'
              and team_relation = 'parent_team' then 0.75
         when report_department = candidate_department
              and report_department <> 'Unclassified' then 0.67
         when candidate_level = 'CEO' then 0.45
         else 0.20 end
         + case when same_location = 1 then 0.002 else 0 end
         as evidence_score
from employee_manager_candidates m
),
employee_top_manager_candidates as materialized (
with ranked as (
    select company_id, employee_id, candidate_id, evidence_score,
           row_number() over (
               partition by company_id, employee_id
               order by evidence_score desc, length(candidate_team) desc,
                        candidate_rank asc, candidate_id
           ) as position
    from employee_manager_scores
)
select e.company_id, e.employee_id,
       max(case when r.position = 1 then r.candidate_id end) as best_candidate_id,
       max(case when r.position = 1 then r.evidence_score end) as best_score,
       max(case when r.position = 2 then r.evidence_score end) as second_score
from employees e
left join ranked r on r.company_id = e.company_id and r.employee_id = e.employee_id
     and r.position <= 2
group by e.company_id, e.employee_id
),
employee_reporting_decisions as materialized (
with scored as (
    select e.company_id, e.employee_id, f.inferred_level,
           t.best_candidate_id as candidate_id,
           round(coalesce(t.best_score, 0.0), 4) as confidence,
           round(max(0.0, coalesce(t.best_score, 0.0) -
                    coalesce(t.second_score, 0.0)), 4) as margin
    from employees e
    join employee_reporting_features f using(company_id, employee_id)
    join employee_top_manager_candidates t using(company_id, employee_id)
)
select company_id, employee_id,
       case when inferred_level <> 'CEO' and confidence >= s.score_threshold
                  and margin >= s.margin_threshold then candidate_id end as accepted_manager_id,
       candidate_id as best_candidate_id,
       min(1.0, confidence) as confidence, margin,
       case when inferred_level = 'CEO' then 'company_root'
            when confidence >= s.score_threshold and margin >= s.margin_threshold then 'accepted'
            else 'unresolved' end as decision
from scored cross join reporting_thresholds s
)
select * from employee_reporting_decisions;
