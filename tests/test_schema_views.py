"""Keep view dependencies complete and match team names literally."""

from pathlib import Path
import sqlite3
import unittest
import xml.etree.ElementTree as ET

from scripts.build_erd import build_diagram, view_dependencies
from scripts.build_company_query import company_query

ROOT = Path(__file__).resolve().parents[1]


class SchemaViewTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript((ROOT / 'schema.sql').read_text())
        self.db.execute("insert into companies values ('example', 'Example', 'Software', 'London')")

    def add(self, name, title, team):
        self.db.execute('insert into employees values (?,?,?,?,?,?,?,?)',
                        ('example', name, name, title, 'Engineering', team, 'London', ''))

    def test_shortlist_keeps_people_without_manager_candidates(self):
        self.add('ceo', 'CEO', 'Company')
        self.add('unassigned', 'Senior Engineer', '')
        shortlist = self.db.execute('select * from employee_top_manager_candidates order by employee_id').fetchall()
        self.assertEqual(shortlist, [('example', 'ceo', None, None, None),
                                     ('example', 'unassigned', 'ceo', 0.452, None)])
        self.assertEqual(self.prediction('unassigned'), (None, 'unresolved'))

    def test_company_query_is_built_from_current_view_rules(self):
        self.assertEqual((ROOT / 'sql/company_predictions.sql').read_text(), company_query())

    def test_analyst_keeps_its_specific_function(self):
        for index, (title, expected) in enumerate([
            ('Product Analyst', 'Product'), ('Operations Analyst', 'Operations'),
            ('Financial Analyst', 'Finance'), ('FP&A Analyst', 'Finance'),
            ('Data Analyst', 'Data & Analytics'), ('Network Engineer', 'IT'),
            ('Cust Success Mgr', 'Customer Success'),
        ]):
            self.add(f'person_{index}', title, '')
            actual = self.db.execute('select inferred_department from employee_reporting_features where employee_id=?',
                                     (f'person_{index}',)).fetchone()[0]
            self.assertEqual(actual, expected, title)

    def prediction(self, employee_id):
        return self.db.execute('select accepted_manager_id, decision from employee_reporting_decisions where employee_id=?',
                               (employee_id,)).fetchone()

    def test_missing_specialist_team_still_respects_the_lead_layer(self):
        self.add('manager', 'Data Engineering Manager', 'Company / Data / Data Platform')
        self.add('lead', 'Data & Analytics Team Lead', 'Company / Data / Data Platform')
        self.add('junior', 'Junior Data Engineer', '')
        self.add('senior', 'Senior Data Engineer', '')
        self.assertEqual(self.prediction('junior'), ('lead', 'accepted'))
        self.assertEqual(self.prediction('senior'), ('manager', 'accepted'))
        self.db.execute("update employees set raw_team='' where employee_id='lead'")
        self.assertEqual(self.prediction('junior'), (None, 'unresolved'))

    def test_duplicate_specialists_and_broad_principal_roles_stay_open(self):
        self.add('first', 'Growth Marketing Manager', 'Company / Growth / First')
        self.add('second', 'Growth Marketing Manager', 'Company / Growth / Second')
        self.add('report', 'Senior Growth Marketer', '')
        self.assertEqual(self.prediction('report'), (None, 'unresolved'))
        self.add('people_manager', 'People Ops Manager', 'Company / People / People Operations')
        self.add('principal', 'Principal People Partner', '')
        self.assertEqual(self.prediction('principal'), (None, 'unresolved'))

    def test_executive_title_recovers_missing_team_without_guessing_between_peers(self):
        self.add('ceo', 'CEO', 'Company')
        self.add('cto', 'CTO', '')
        self.add('vp', 'VP Engineering', 'Company / Technology / Engineering')
        self.assertEqual(self.prediction('vp'), ('cto', 'accepted'))
        self.add('second_cto', 'Chief Technology Officer', '')
        self.assertEqual(self.prediction('vp'), (None, 'unresolved'))

    def test_a_missing_executive_title_blocks_a_ceo_shortcut(self):
        self.add('ceo', 'CEO', 'Company')
        self.add('vp', 'VP Engineering', 'Company / Technology / Engineering')
        self.add('unknown', '', 'Company / Technology')
        self.assertEqual(self.prediction('vp'), (None, 'unresolved'))

    def test_title_match_does_not_override_two_conflicting_known_teams(self):
        self.add('manager', 'QA Manager', 'Company / QA / First')
        self.add('report', 'Senior QA Engineer', 'Company / QA / Second')
        self.assertEqual(self.prediction('report'), (None, 'unresolved'))

    def test_source_keys_and_cross_company_rows_are_not_matching_features(self):
        self.db.execute("insert into companies values ('other', 'Other', 'Software', 'London')")
        self.db.execute("insert into employees values ('other','manager','Manager','QA Manager','Engineering','Company / QA','London','')")
        self.add('report', 'Senior QA Engineer', '')
        self.assertEqual(self.prediction('report'), (None, 'unresolved'))

    def test_team_underscores_do_not_match_another_team(self):
        self.add('manager', 'Engineering Manager', 'Company / Sales_Ops')
        self.add('report', 'Senior Engineer', 'Company / SalesXOps / Platform')
        self.assertEqual(self.db.execute("select count(*) from employee_manager_candidates where employee_id='report'").fetchone()[0], 0)

    def test_team_percent_does_not_match_another_team(self):
        self.add('manager', 'Engineering Manager', 'Company / 100%')
        self.add('report', 'Senior Engineer', 'Company / 1000 / Platform')
        self.assertEqual(self.db.execute("select count(*) from employee_manager_candidates where employee_id='report'").fetchone()[0], 0)

    def test_literal_parent_team_still_matches(self):
        self.add('manager', 'Engineering Manager', 'Company / 100%_Ops')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        row = self.db.execute("select candidate_id, team_relation from employee_manager_candidates where employee_id='report'").fetchone()
        self.assertEqual(row, ('manager', 'parent_team'))

    def test_missing_team_labels_are_not_matching_evidence(self):
        for index, team in enumerate(['', '-', 'n/a', 'unknown']):
            self.add(f'manager_{index}', 'Engineering Manager', team)
            self.add(f'report_{index}', 'Senior Engineer', team)
        self.assertEqual(self.db.execute('select count(*) from employee_manager_candidates').fetchone()[0], 0)

    def test_missing_team_specialist_fallback_requires_a_unique_manager(self):
        self.add('qa_manager', 'QA Manager', 'Engineering / QA')
        self.add('qa_report', 'Junior QA Engineer', '')
        self.add('security_manager', 'Security Engineering Manager', 'Engineering / Security')
        self.add('security_report', 'Security Engineer', 'n/a')

        query = (ROOT / 'sql/company_predictions.sql').read_text()
        def decision(sql):
            return self.db.execute(sql, {'company_id': 'example'}).fetchall()

        public = self.db.execute("select accepted_manager_id, decision from employee_reporting_decisions where employee_id='qa_report'").fetchone()
        self.assertEqual(public, ('qa_manager', 'accepted'))
        security = self.db.execute("select accepted_manager_id, decision from employee_reporting_decisions where employee_id='security_report'").fetchone()
        self.assertEqual(security, ('security_manager', 'accepted'))
        self.assertEqual(sorted(decision(query)), sorted(self.db.execute('select * from employee_reporting_decisions').fetchall()))

        self.add('second_qa_manager', 'QA Engineering Manager', 'Engineering / Quality')
        public = self.db.execute("select accepted_manager_id, decision from employee_reporting_decisions where employee_id='qa_report'").fetchone()
        self.assertEqual(public, (None, 'unresolved'))
        security = self.db.execute("select accepted_manager_id, decision from employee_reporting_decisions where employee_id='security_report'").fetchone()
        self.assertEqual(security, ('security_manager', 'accepted'))
        self.assertEqual(sorted(decision(query)), sorted(self.db.execute('select * from employee_reporting_decisions').fetchall()))

    def test_company_query_and_public_views_agree(self):
        self.add('ceo', 'CEO', 'Company')
        self.add('manager', 'Engineering Manager', 'Company / 100%_Ops')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        self.add('other', 'Senior Engineer', 'Company / 1000 / Platform')
        scoped = self.db.execute((ROOT / 'sql/company_predictions.sql').read_text(), {'company_id': 'example'}).fetchall()
        public = self.db.execute('select * from employee_reporting_decisions').fetchall()
        self.assertEqual(sorted(scoped), sorted(public))

    def test_queries_leave_the_observed_rows_unchanged(self):
        self.add('manager', '  Engineering Mgr. ', ' Company / 100%_Ops ')
        self.add('report', 'Senior Engineer', 'Company / 100%_Ops / Platform')
        before = self.db.execute('select * from employees order by employee_id').fetchall()
        self.db.execute('select * from employee_reporting_audit').fetchall()
        self.assertEqual(before, self.db.execute('select * from employees order by employee_id').fetchall())

    def test_diagram_includes_every_object_column_and_direct_input(self):
        import json
        build_diagram()
        metadata = json.loads((ROOT / 'public/database-schema.json').read_text())
        objects = {row[0] for row in self.db.execute("select name from sqlite_master where type in ('table','view')")}
        svg = ET.parse(ROOT / 'public/database-erd.svg').getroot()
        ns = {'s': 'http://www.w3.org/2000/svg'}
        entities = {group.attrib['data-name']: group for group in svg.findall('s:g', ns)
                    if group.attrib.get('class') == 'entity'}
        self.assertEqual(objects, set(entities))
        self.assertEqual(len(metadata['tables']), 2)
        self.assertEqual(len(metadata['views']), 12)
        for name, group in entities.items():
            fields = [node.text for node in group.findall('s:text', ns) if node.attrib.get('class') == 'column']
            expected = [row[1] for row in self.db.execute(f'pragma table_info("{name}")')]
            self.assertEqual(fields, expected, name)
        dependencies = view_dependencies(metadata['tables'], metadata['views'])
        actual = {(edge.attrib['data-parent'], edge.attrib['data-child']) for edge in svg.findall('s:path', ns) if edge.attrib.get('data-kind') == 'view-input'}
        self.assertEqual(actual, {(parent, child) for child, parents in dependencies.items() for parent in parents})
        self.assertIn(('employee_top_manager_candidates', 'employee_reporting_decisions'), actual)
        self.assertIn(('employee_reporting_decisions', 'employee_reporting_audit'), actual)
        self.assertNotIn(('scored', 'employee_reporting_decisions'), actual)
