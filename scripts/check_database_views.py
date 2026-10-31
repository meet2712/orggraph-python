"""Check that summary views finish and agree with employee decisions."""

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

ROOT = Path(__file__).resolve().parents[1]


def check_views(database, timeout=20):
    timings = {}
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute('pragma query_only = on')

        def query(name, sql):
            started = time.monotonic()
            connection.set_progress_handler(lambda: time.monotonic() - started > timeout, 1000)
            try:
                rows = connection.execute(sql).fetchall()
            except sqlite3.OperationalError as error:
                if str(error) == 'interrupted':
                    raise ValueError(f'{name} exceeded the {timeout:g} second query limit') from error
                raise
            finally:
                connection.set_progress_handler(None, 0)
            timings[name] = round(time.monotonic() - started, 3)
            return rows

        employee_count = connection.execute('select count(*) from employees').fetchone()[0]
        company_count = connection.execute('select count(*) from companies').fetchone()[0]
        decisions = query('employee_reporting_decisions', '''
            select count(*) as employees, count(distinct company_id || ':' || employee_id) as people,
                   sum(decision = 'accepted') as accepted,
                   sum(decision = 'unresolved') as unresolved
            from employee_reporting_decisions
        ''')[0]
        summaries = query('company_reporting_summary', '''
            select count(*) as companies, sum(resolved_count) as accepted,
                   sum(unresolved_count) as unresolved from company_reporting_summary
        ''')[0]
        totals = query('dataset_reporting_summary', 'select * from dataset_reporting_summary')[0]
        if decisions['employees'] != employee_count or decisions['people'] != employee_count:
            raise ValueError('Reporting decisions do not match the employee rows')
        if summaries['companies'] != company_count or totals['company_count'] != company_count:
            raise ValueError('Summary views do not cover every company')
        if totals['employee_count'] != employee_count:
            raise ValueError('Dataset headcount does not match the source')
        if (summaries['accepted'], summaries['unresolved']) != (decisions['accepted'], decisions['unresolved']):
            raise ValueError('Company summaries disagree with reporting decisions')
        if (totals['accepted_count'], totals['unresolved_count']) != (decisions['accepted'], decisions['unresolved']):
            raise ValueError('Dataset summary disagrees with reporting decisions')
    return {'companies': company_count, 'employees': employee_count, 'seconds': timings}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=ROOT / 'instance/orggraph.sqlite3')
    parser.add_argument('--timeout', type=float, default=20)
    options = parser.parse_args()
    print(json.dumps(check_views(options.database, options.timeout), indent=2))
