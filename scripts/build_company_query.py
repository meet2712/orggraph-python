"""Build the fast company lookup from the public view definitions."""

from contextlib import closing
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (
    'employee_role_classification', 'employee_reporting_features',
    'employee_manager_candidates', 'employee_manager_scores',
    'employee_top_manager_candidates', 'employee_reporting_decisions',
)


def company_query():
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.executescript((ROOT / 'schema.sql').read_text())
        parts = ['employees as materialized (\n'
                 '    select * from main.employees where company_id = :company_id\n)']
        for name in VIEWS:
            definition, = connection.execute(
                "select sql from sqlite_master where type='view' and name=?", (name,)
            ).fetchone()
            select = re.split(r'\s+as\s*\n', definition, maxsplit=1,
                              flags=re.IGNORECASE)[1].rstrip(';')
            parts.append(f'{name} as materialized (\n{select}\n)')
    return ('-- Generated from schema.sql by scripts/build_company_query.py.\n'
            '-- Scope the source rows first; all decision rules stay in the views.\n'
            'with ' + ',\n'.join(parts) + '\nselect * from employee_reporting_decisions;\n')


if __name__ == '__main__':
    (ROOT / 'sql/company_predictions.sql').write_text(company_query())
