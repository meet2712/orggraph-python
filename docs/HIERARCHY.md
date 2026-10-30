# Hierarchy policy

The generated answer key uses two separate career tracks. A higher IC title is
not automatically a people-management title.

## People-management track

```text
CEO
└── C-suite executive
    └── VP or Head of function
        └── Senior Director (optional)
            └── Director (optional)
                └── Senior Manager (optional)
                    └── Manager
                        └── Team Lead or Supervisor (optional)
```

Layers are size-aware and may be skipped. A company with 100 employees should
not have the same management depth as a company with 250 employees. The
generator never creates a same-level reporting edge.

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

- The CEO manages a small executive portfolio rather than every department.
- C-suite executives own Technology, Revenue, Operations, Finance & Risk, or
  People portfolios.
- Department VPs/Heads report to the corresponding executive.
- Directors own functions or multiple teams; Managers own one delivery team.
- QA Engineers and QA Team Leads report through a QA Manager before joining the
  broader Engineering branch.
- Team names form a containment path, for example
  `Company / Technology / Engineering / Quality & Reliability / Quality`.

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

`pipeline/validate_hierarchy.py` checks a held-out sample of 75 companies and
fails when:

- a manager is not more senior than the report;
- an IC receives direct reports;
- a people manager has no reports;
- a reporting edge violates the allowed management ladder;
- a QA delivery edge leaves the QA branch;
- an accepted prediction points to a non-manager title; or
- accepted precision falls below the configured quality floor.

`pipeline/validate_dataset.py` additionally checks all 500 companies for one
CEO root, acyclic reporting lines, same-company edges and nested team scope.
