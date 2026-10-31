# Hierarchy policy

The generated answer key uses two separate career tracks. A higher IC title is
not automatically a people-management title.

## People-management track

```text
CEO
├── C-suite executive (when that portfolio exists)
│   └── VP or Head of function
└── VP or Head of function (when no matching executive exists)
        └── Senior Director (optional)
            └── Director (optional)
                └── Senior Manager (optional)
                    └── Manager
                        └── Team Lead or Supervisor (optional)
```

Layers are size-aware and may be skipped. The CEO is universal; CTO, CRO, COO,
CFO and CPO are not. Small companies have one or two non-CEO executives,
Growth companies two to four, and Mid-market companies three to five. Industry
weights make Technology more likely in technical companies, Operations in
logistics-heavy companies, and Finance & Risk in regulated companies. The
selection is seeded and reproducible. The generator never creates a same-level
reporting edge.

## Individual-contributor track

```text
Junior → Intermediate → Senior → Staff → Principal
```

This is a progression of scope, not a reporting chain. Senior, Staff and
Principal employees remain ICs and normally report to a Manager. Junior and
Intermediate employees may report to an explicit Team Lead or Supervisor when
the team is large enough. An IC never receives direct reports in the generated
ground truth.

Titles that contain `Manager` can still be IC roles. Product Manager, Account
Manager and Customer Success Manager are treated as IC titles unless another
explicit management cue identifies a people-management role.

## Functional ownership

- The CEO manages the available executive portfolio and any functions that do
  not have a dedicated C-suite owner.
- C-suite executives own Technology, Revenue, Operations, Finance & Risk, or
  People portfolios.
- Department VPs/Heads report to the corresponding executive when present;
  otherwise they report to the CEO.
- Directors own functions or multiple teams; Managers own one delivery team.
- QA Engineers and QA Team Leads report through a QA Manager before joining the
  broader Engineering branch.
- Team names form a containment path, for example
  `Company / Technology / Engineering / Quality & Reliability / Quality`.

## Live inference rule

The operational database derives features and manager choices in SQL views.
It normalizes explicit management titles, filters to more-senior candidates in
the same company, and scores team scope and function evidence. A candidate is
accepted only when the evidence score and its lead over the next candidate
clear the thresholds in the `reporting_thresholds` view. Ties and missing evidence
remain unresolved. The evidence score is a heuristic rather than a calibrated
probability. Senior, Staff and Principal IC titles do not become managers just
because of their seniority.

The original generated employee population is retained. Rows that previously
forced an unnecessary specialist executive into a company become functional
Principal IC roles under the relevant VP/Head. In the messy input only their
observed title changes; IDs, names, emails, observed departments, teams and
locations remain unchanged.

## Research basis

The policy is a synthetic default, not a claim that every real company uses one
universal structure. It is based on these public examples:

- [GitLab organizational structure](https://handbook.gitlab.com/handbook/company/structure/)
  separates the people-manager and IC tracks, places VP above Director and
  Manager, and says layers may be skipped but generally should not report to the
  same layer.
- [GitLab engineering leadership](https://handbook.gitlab.com/job-description-library/engineering/development/management/)
  documents Engineering Manager, Senior Engineering Manager, Director, Senior
  Director and VP roles, including managers-of-managers.
- [GitLab development career framework](https://handbook.gitlab.com/handbook/engineering/careers/matrix/development/)
  lists Intermediate, Senior, Staff and Principal as engineering IC levels,
  separate from Engineering Manager and Director roles.
- [Taunton Town Council staff structure](https://services.taunton-tc.gov.uk/orgchart/table)
  is a public `reports to` dataset showing real examples of Chief Executive →
  Deputy Chief Executive → Head → Lead/Supervisor → Officer/Assistant chains.

Sources were reviewed on 30 October 2026.

## Automated checks

`pipeline/validate_dataset.py` checks the generated source and answer key.
`scripts/quality_checks.sql` checks the current SQL view output for key
integrity, decision consistency, seniority, and cycles.
`scripts/evaluate_sql_inference.py` compares accepted SQL decisions with the
separate answer key on 75 held-out companies and enforces the precision floor.
The dataset validator checks all 500 generated companies for one CEO root,
acyclic reporting lines, same-company edges and nested team scope.
