"""Keep view dependencies complete and match team names literally."""

from pathlib import Path
import sqlite3
import unittest
import xml.etree.ElementTree as ET

from scripts.build_erd import build_diagram, view_dependencies

ROOT = Path(__file__).resolve().parents[1]


class SchemaViewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript((ROOT / 'schema.sql').read_text())
        self.db.execute("INSERT INTO companies VALUES ('example', 'Example', 'Software', 'London')")

    def add(self, name, title, team):
        self.db.execute('INSERT INTO employees VALUES (?,?,?,?,?,?,?,?)',
                        ('example', name, name, title, 'Engineering', team, 'London', ''))

    def test_team_underscores_do_not_match_another_team(self):
        self.add('manager', 'Engineering Manager', 'Company / Sales_Ops')
        self.add('report', 'Senior Engineer', 'Company / SalesXOps / Platform')
        self.assertEqual(self.db.execute("SELECT count(*) FROM manager_candidates WHERE employee_id='report'").fetchone()[0], 0)

    def test_team_percent_does_not_match_another_team(self):
        self.add('manager', 'Engineering Manager', 'Company / 100%')
        self.add('report', 'Senior Engineer', 'Company / 1000 / Platform')
        self.assertEqual(self.db.execute("SELECT count(*) FROM manager_candidates WHERE employee_id='report'").fetchone()[0], 0)

    def test_literal_parent_team_still_matches(self):
        self.add('manager', 'Engineering Manager', 'Company / 100%_Ops')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        row = self.db.execute("SELECT candidate_id, team_relation FROM manager_candidates WHERE employee_id='report'").fetchone()
        self.assertEqual(row, ('manager', 'parent_team'))

    def test_missing_team_labels_are_not_matching_evidence(self):
        for index, team in enumerate(['', '-', 'n/a', 'unknown']):
            self.add(f'manager_{index}', 'Engineering Manager', team)
            self.add(f'report_{index}', 'Senior Engineer', team)
        self.assertEqual(self.db.execute('SELECT count(*) FROM manager_candidates').fetchone()[0], 0)

    def test_company_query_and_public_views_agree(self):
        self.add('ceo', 'CEO', 'Company')
        self.add('manager', 'Engineering Manager', 'Company / 100%_Ops')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        self.add('other', 'Senior Engineer', 'Company / 1000 / Platform')
        scoped = self.db.execute((ROOT / 'sql/company_predictions.sql').read_text(), {'company_id': 'example'}).fetchall()
        public = self.db.execute('SELECT * FROM reporting_predictions').fetchall()
        self.assertEqual(sorted(scoped), sorted(public))

    def test_queries_leave_the_observed_rows_unchanged(self):
        self.add('manager', '  Engineering Mgr. ', ' Company / 100%_Ops ')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        before = self.db.execute('SELECT * FROM employees ORDER BY employee_id').fetchall()
        self.db.execute('SELECT * FROM employee_reporting_audit').fetchall()
        self.assertEqual(before, self.db.execute('SELECT * FROM employees ORDER BY employee_id').fetchall())

    def test_diagram_includes_every_object_column_and_direct_input(self):
        import json
        build_diagram()
        metadata = json.loads((ROOT / 'public/database-schema.json').read_text())
        objects = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        svg = ET.parse(ROOT / 'public/database-erd.svg').getroot()
        ns = {'s': 'http://www.w3.org/2000/svg'}
        entities = {group.attrib['data-name']: group for group in svg.findall('s:g', ns)
                    if group.attrib.get('class') == 'entity'}
        self.assertEqual(objects, set(entities))
        self.assertEqual(len(metadata['tables']), 2)
        self.assertEqual(len(metadata['views']), 13)
        for name, group in entities.items():
            fields = [node.text for node in group.findall('s:text', ns) if node.attrib.get('class') == 'column']
            expected = [row[1] for row in self.db.execute(f'PRAGMA table_info("{name}")')]
            self.assertEqual(fields, expected, name)
        dependencies = view_dependencies(metadata['tables'], metadata['views'])
        actual = {(edge.attrib['data-parent'], edge.attrib['data-child']) for edge in svg.findall('s:path', ns) if edge.attrib.get('data-kind') == 'view-input'}
        self.assertEqual(actual, {(parent, child) for child, parents in dependencies.items() for parent in parents})
        self.assertIn(('employee_top_candidates', 'reporting_predictions'), actual)
        self.assertIn(('reporting_predictions', 'employee_reporting_audit'), actual)
        self.assertNotIn(('scored', 'reporting_predictions'), actual)
