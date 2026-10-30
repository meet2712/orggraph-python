"""Build the fast company lookup from the public view definitions."""

from contextlib import closing
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
VIEWS = (
    'employee_text', 'employee_classification', 'employee_role_profiles', 'employee_features',
    'manager_candidates', 'candidate_scores', 'employee_top_candidates',
    'reporting_predictions',
)


def company_query():
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.executescript((ROOT / 'schema.sql').read_text())
        parts = ['employees AS MATERIALIZED (\n'
                 '    SELECT * FROM main.employees WHERE company_id = :company_id\n)']
        for name in VIEWS:
            definition, = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type='view' AND name=?", (name,)
            ).fetchone()
            select = definition.split(' AS\n', 1)[1].rstrip(';')
            parts.append(f'{name} AS MATERIALIZED (\n{select}\n)')
    return ('-- Generated from schema.sql by scripts/build_company_query.py.\n'
            '-- Scope the source rows first; all decision rules stay in the views.\n'
            'WITH ' + ',\n'.join(parts) + '\nSELECT * FROM reporting_predictions;\n')


if __name__ == '__main__':
    (ROOT / 'sql/company_predictions.sql').write_text(company_query())
