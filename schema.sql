pragma foreign_keys = on;

-- Only observed source records are stored. Every other object below is a
-- read-only view, recalculated when an employee is inserted or changed.
create table companies (
    company_id TEXT primary key,
    company_name TEXT not null,
    industry TEXT not null,
    headquarters TEXT not null
);

create table employees (
    company_id TEXT not null references companies(company_id),
    employee_id TEXT not null,
    full_name TEXT not null,
    job_title TEXT not null,
    raw_department TEXT not null,
    raw_team TEXT not null,
    location TEXT not null,
    work_email TEXT not null,
    primary key (company_id, employee_id)
);

create index employees_by_company_team on employees(company_id, raw_team);

-- Central thresholds used by every reporting decision.
create view reporting_thresholds as
select 0.98 as score_threshold, 0.04 as margin_threshold;

create view company_overview as
select c.company_id, c.company_name, c.industry,
       case when count(e.employee_id) < 130 then 'Small'
            when count(e.employee_id) < 180 then 'Growth'
            else 'Mid-market' end as size_band,
       count(e.employee_id) as employee_count, c.headquarters
from companies c left join employees e using(company_id)
group by c.company_id;

-- Classify each observed role. Normalize title and team text inside this view;
-- the original employee row stays untouched and answer-key fields never enter.
create view employee_role_classification as
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
from text t;

-- Add a narrow specialty, executive portfolio, and leadership rank to each
-- classified employee. These are matching features, not saved source fields.
create view employee_reporting_features as
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
             when title_text like '% backend %' or title_text like '% back end %'
               or title_text like '% frontend %' or title_text like '% front end %'
               or title_text like '% full stack %' or title_text like '% fullstack %'
               or title_text like '% software engineer %'
               or title_text like '% software engineering %'
               or title_text like '% software developer %'
               or title_text like '% software development %'
               or title_text like '% software eng %' then 'software_engineering'
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
from role_profiles p;

-- Candidate set stays inside one company and permits only explicit managers.
-- A management role may report to the next available higher layer. ICs can
-- report to an explicit Team Lead or Manager, but never to a Senior IC.
create view employee_manager_candidates as
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
          and r.role_family not in ('','software_engineering')
          and r.role_family = c.role_family)
  );

-- Every way a manager can be matched, with the score it earns. The scoring
-- view names the first rule that fits; this table turns the name into a score.
-- Rules at or above score_threshold can be accepted on their own. The weak
-- rules only decide which candidate is shown for people left unresolved.
create view reporting_rules as
with rules(rule, score, rule_group, description) as (values
    ('exec_to_ceo',         0.995, 'executive', 'Executive reports to the CEO'),
    ('vp_to_matching_exec', 0.99,  'executive', 'VP/Head reports to the executive who owns their portfolio'),
    ('vp_to_ceo_no_exec',   0.99,  'executive', 'VP/Head reports to the CEO because no executive owns their portfolio'),
    ('director_to_vp',      0.99,  'ladder',    'Director reports to the VP/Head of the same function'),
    ('manager_to_director', 0.99,  'ladder',    'Manager reports to the Director of the same function; no Senior Manager in between'),
    ('manager_to_vp',       0.99,  'ladder',    'Manager reports to the VP/Head of the same function; no Director or Senior Manager in between'),
    ('next_level_up',       0.99,  'ladder',    'Management role reports to the next level up on the same or parent team'),
    ('lead_to_manager',     0.995, 'team',      'Team Lead reports to the Manager of the same team'),
    ('junior_to_lead',      0.995, 'team',      'Junior or intermediate IC reports to the Team Lead of the same team'),
    ('junior_to_manager',   0.99,  'team',      'Junior or intermediate IC reports to the same-team Manager; the function has no Team Lead'),
    ('senior_to_manager',   0.99,  'team',      'Senior, Staff or Principal IC reports to the Manager of the same team'),
    ('specialty_match',     0.995, 'specialty', 'Team is missing on one side, but the IC and the manager share a specific specialty'),
    ('ceo_only',            0.45,  'weak',      'the CEO, who is a candidate for everyone'),
    ('same_team_only',      0.90,  'weak',      'same team, but no rule above applies'),
    ('parent_team_only',    0.85,  'weak',      'parent team, but no rule above applies'),
    ('same_function_only',  0.67,  'weak',      'same function, different team'),
    ('title_only',          0.45,  'weak',      'a management title above this person, nothing else')
)
select * from rules;

-- Hand-set scores. The first matching branch wins; the ordering matters.
create view employee_manager_scores as
with features as materialized (select * from employee_reporting_features),
     matched as materialized (
    select m.company_id, m.employee_id, m.candidate_id,
           m.candidate_rank, m.candidate_team, m.same_location,
       case
         -- No team on one side, but a specific specialty on both. The margin
         -- check in employee_reporting_decisions handles two equal matches.
         when report_family not in ('','software_engineering')
              and report_family = candidate_family
              and report_level in ('Junior IC','Individual Contributor','Senior IC','Principal / Staff IC')
              and candidate_level in ('Manager','Team Lead / Supervisor')
              and (report_team in ('','n/a','unknown','-') or candidate_team in ('','n/a','unknown','-')
                   or team_relation = 'parent_team')
              -- "Principal People Partner" could sit under any People manager.
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
              ) <= 1) then 'specialty_match'
         when report_level = 'VP / Head' and candidate_level = 'C-Suite'
              and report_portfolio <> '' and report_portfolio = candidate_portfolio
              then 'vp_to_matching_exec'
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
              ) then 'vp_to_ceo_no_exec'
         when report_level = 'C-Suite' and candidate_level = 'CEO' then 'exec_to_ceo'
         when report_level in ('Junior IC','Individual Contributor')
              and candidate_level = 'Team Lead / Supervisor'
              and team_relation = 'same_team' then 'junior_to_lead'
         when report_level in ('Senior IC','Principal / Staff IC')
              and candidate_level = 'Manager'
              and team_relation = 'same_team' then 'senior_to_manager'
         when report_level = 'Team Lead / Supervisor'
              and candidate_level = 'Manager'
              and team_relation = 'same_team' then 'lead_to_manager'
         -- Same-team manager for an IC, as long as there is no team lead in
         -- the function who would normally sit in between.
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
              ) then 'junior_to_manager'
         -- Skipping a layer is only fine when that layer does not exist here.
         when report_level = 'Director' and candidate_level = 'VP / Head'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team') then 'director_to_vp'
         when report_level = 'Manager' and candidate_level = 'Director'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team')
              and not exists (
                  select 1 from features intermediate
                  where intermediate.company_id = m.company_id
                    and intermediate.inferred_department = m.report_department
                    and intermediate.inferred_level = 'Senior Manager'
              ) then 'manager_to_director'
         when report_level = 'Manager' and candidate_level = 'VP / Head'
              and report_department = candidate_department
              and report_department <> 'Unclassified'
              and team_relation in ('same_team','parent_team')
              and not exists (
                  select 1 from features intermediate
                  where intermediate.company_id = m.company_id
                    and intermediate.inferred_department = m.report_department
                    and intermediate.inferred_level in ('Director','Senior Manager')
              ) then 'manager_to_vp'
         -- Generic step up the ladder. A VP never attaches to an executive
         -- whose portfolio is known to be a different one.
         when report_rank >= 4 and candidate_rank = report_rank + 1
              and team_relation in ('same_team','parent_team')
              and not (candidate_level = 'C-Suite' and candidate_portfolio <> ''
                       and report_portfolio <> candidate_portfolio)
              then 'next_level_up'
         -- Nothing below here can be accepted on its own. These only rank the
         -- leading candidate shown for people who stay unresolved.
         when candidate_level = 'CEO' then 'ceo_only'
         when team_relation = 'same_team' then 'same_team_only'
         when team_relation = 'parent_team' then 'parent_team_only'
         when report_department = candidate_department
              and report_department <> 'Unclassified' then 'same_function_only'
         else 'title_only' end as rule
    from employee_manager_candidates m
)
select matched.company_id, matched.employee_id, matched.candidate_id,
       matched.candidate_rank, matched.candidate_team, matched.rule,
       rules.score + case when matched.same_location = 1 then 0.002 else 0 end
         as evidence_score
from matched left join reporting_rules rules using (rule);

-- Best and second-best per employee; the gap between them is the margin.
create view employee_top_manager_candidates as
with ranked as (
    select company_id, employee_id, candidate_id, rule, evidence_score,
           row_number() over (
               partition by company_id, employee_id
               order by evidence_score desc, length(candidate_team) desc,
                        candidate_rank asc, candidate_id
           ) as position
    from employee_manager_scores
)
select e.company_id, e.employee_id,
       max(case when r.position = 1 then r.candidate_id end) as best_candidate_id,
       max(case when r.position = 1 then r.rule end) as best_rule,
       max(case when r.position = 1 then r.evidence_score end) as best_score,
       max(case when r.position = 2 then r.evidence_score end) as second_score
from employees e
left join ranked r on r.company_id = e.company_id and r.employee_id = e.employee_id
     and r.position <= 2
group by e.company_id, e.employee_id;

-- Accept the best candidate only when the score clears the threshold and the
-- runner-up is clearly behind. Everyone else stays unresolved, with a reason.
create view employee_reporting_decisions as
with scored as (
    select e.company_id, e.employee_id, f.inferred_level,
           t.best_candidate_id as candidate_id, t.best_rule as rule,
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
            else 'unresolved' end as decision,
       rule,
       case when inferred_level = 'CEO' then 'CEO is the company root'
            when candidate_id is null then 'No management title above this person'
            when confidence >= s.score_threshold and margin >= s.margin_threshold then r.description
            when confidence < s.score_threshold then 'Only weak evidence: ' || r.description
            else 'Two candidates fit equally well: '
                 || lower(substr(r.description, 1, 1)) || substr(r.description, 2)
            end as reason
from scored
cross join reporting_thresholds s
left join reporting_rules r using (rule);

create view company_reporting_summary as
select p.company_id,
       sum(p.decision = 'accepted') as resolved_count,
       sum(p.decision = 'unresolved') as unresolved_count,
       round(1.0 * sum(p.decision = 'accepted') /
             max(sum(p.decision <> 'company_root'), 1), 4) as coverage,
       round(coalesce(avg(case when p.decision = 'accepted'
             then p.confidence end), 0), 4) as average_confidence
from employee_reporting_decisions p group by p.company_id;

create view dataset_reporting_summary as
select count(distinct company_id) as company_count,
       count(*) as employee_count,
       sum(decision = 'accepted') as accepted_count,
       sum(decision = 'unresolved') as unresolved_count,
       round(coalesce(avg(case when decision = 'accepted'
             then confidence end), 0), 4) as average_resolved_confidence
from employee_reporting_decisions;

-- One row per person with the raw record, what was inferred, who was chosen
-- and why. This is the view to query when a reporting line looks wrong.
create view employee_reporting_audit as
select e.company_id, e.employee_id, e.full_name, e.job_title,
       e.raw_department, e.raw_team, e.location,
       f.inferred_department, f.inferred_level,
       p.accepted_manager_id, manager.full_name as inferred_manager,
       p.best_candidate_id, candidate.full_name as leading_candidate,
       p.confidence, p.margin, p.decision, p.rule, p.reason,
       s.score_threshold, s.margin_threshold
from employee_reporting_decisions p
join employees e using(company_id, employee_id)
join employee_reporting_features f using(company_id, employee_id)
cross join reporting_thresholds s
left join employees manager on manager.company_id = p.company_id
      and manager.employee_id = p.accepted_manager_id
left join employees candidate on candidate.company_id = p.company_id
      and candidate.employee_id = p.best_candidate_id;
