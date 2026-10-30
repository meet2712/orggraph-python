"""Build the portal's schema diagram from SQLite's own key definitions."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
GRID = {'companies': (0, 0), 'employees': (0, 1)}
GRAINS = {
    'companies': 'One company', 'employees': 'One observed employee',
}
VIEW_GRAINS = {
    'company_profiles': 'One live company profile',
    'employee_features': 'One live feature set per employee',
    'reporting_predictions': 'One live decision per employee',
    'prediction_reasons': 'One explanation signal per decision',
    'company_run_metrics': 'One live company summary',
    'run_metrics': 'One live database summary',
    'employee_reporting_audit': 'One inspectable decision per employee',
    'inference_runs': 'Current SQL rules and thresholds',
    'employee_text': 'Normalized title and source text',
    'employee_classification': 'Title-derived function and seniority',
    'manager_candidates': 'Plausible manager pairs',
    'candidate_scores': 'Evidence score for each pair',
    'employee_top_candidates': 'Best and second-best candidate',
}


def view_dependencies(tables, views):
    """List the real table/view inputs in each saved CREATE VIEW statement."""
    names = {item['name'] for item in [*tables, *views]}
    dependencies = {}
    for view in views:
        references = re.findall(r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z_0-9]*)',
                                view['definition'], flags=re.IGNORECASE)
        dependencies[view['name']] = [name for name in dict.fromkeys(references)
                                      if name in names and name != view['name']]
    return dependencies


def render_view_flow(tables, views, dependencies):
    """Draw the five-stage read path without crossing every SQL join."""
    stages = [
        ('1 · SOURCE', ['companies', 'employees', 'inference_runs']),
        ('2 · PREPARE', ['employee_text', 'employee_classification', 'employee_features']),
        ('3 · MATCH', ['manager_candidates', 'candidate_scores', 'employee_top_candidates']),
        ('4 · DECIDE', ['reporting_predictions', 'prediction_reasons']),
        ('5 · INSPECT', ['company_profiles', 'company_run_metrics',
                         'run_metrics', 'employee_reporting_audit']),
    ]
    objects = {item['name'] for item in [*tables, *views]}
    shown = [name for _, stage in stages for name in stage]
    if set(shown) != objects or len(shown) != len(objects):
        raise ValueError(f'Update view flow stages: missing {objects - set(shown)}, '
                         f'extra {set(shown) - objects}')
    descriptions = {
        'companies': 'Company details',
        'employees': 'Messy employee records',
        'inference_runs': 'Current SQL thresholds',
        'employee_text': 'Normalize title and team text',
        'employee_classification': 'Function and seniority',
        'employee_features': 'One feature set per person',
        'manager_candidates': 'Plausible same-company leaders',
        'candidate_scores': 'Evidence for each candidate',
        'employee_top_candidates': 'Best and second-best candidate',
        'reporting_predictions': 'Accept a link or abstain',
        'prediction_reasons': 'Explain the decision',
        'company_profiles': 'Headcount and size band',
        'company_run_metrics': 'Per-company coverage',
        'run_metrics': 'Overall counts and mean score',
        'employee_reporting_audit': 'Inspect an employee decision',
    }
    width, height, card_width, card_height = 1810, 640, 318, 96
    left, column_step, first_card_y, card_step = 28, 356, 166, 104
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">How source tables feed the SQL reporting views</title>',
        '<desc id="desc">Five stages run left to right: source tables, title preparation, manager matching, reporting decisions, and inspection. Every view card names its exact direct inputs. Views read source rows on demand and never copy them.</desc>',
        '<defs><marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0 0 L10 5 L0 10 Z" fill="#4b7965"/></marker></defs>',
        f'<rect width="{width}" height="{height}" fill="#f7f9f6"/>',
        '<style>text{font-family:system-ui,sans-serif;fill:#283c32}'
        '.heading{font-size:19px;font-weight:700}.note{font-size:12px;fill:#526159}'
        '.stage{font-size:13px;font-weight:700;letter-spacing:.07em;fill:#315c49}'
        '.name{font-size:15px;font-weight:700}.description{font-size:12px;fill:#506159}'
        '.reads{font-family:ui-monospace,monospace;font-size:11px;fill:#5b6b5d}'
        '.kind{font-size:10px;font-weight:700;fill:#376c50}</style>',
        '<text x="28" y="35" class="heading">Two source tables → live reporting views</text>',
        '<text x="28" y="58" class="note">Arrows trace the main reporting path. Side views can read source tables directly; each “Reads” line gives the exact inputs.</text>',
    ]
    for stage_index, (title, names) in enumerate(stages):
        x = left + stage_index * column_step
        lines.extend([
            f'<rect x="{x - 8}" y="105" width="{card_width + 16}" height="480" '
            'rx="9" fill="#f0f4ef" stroke="#dae5da"/>',
            f'<text x="{x + 7}" y="137" class="stage">{escape(title)}</text>',
        ])
        if stage_index < len(stages) - 1:
            next_x = left + (stage_index + 1) * column_step
            lines.append(f'<path d="M{x + card_width + 6},128 H{next_x - 15}" '
                         'fill="none" stroke="#4b7965" stroke-width="2.5" '
                         'marker-end="url(#flow-arrow)"/>')
        for item_index, name in enumerate(names):
            y = first_card_y + item_index * card_step
            stored = name in {'companies', 'employees'}
            fill = '#e4efe6' if stored else '#ffffff'
            stroke = '#80a98b' if stored else '#b9cbbd'
            lines.extend([
                f'<g aria-label="{escape(name)}">',
                f'<rect x="{x}" y="{y}" width="{card_width}" height="{card_height}" '
                f'rx="7" fill="{fill}" stroke="{stroke}"/>',
                f'<text x="{x + 12}" y="{y + 21}" class="name">{escape(name)}</text>',
                f'<text x="{x + 12}" y="{y + 41}" class="description">'
                f'{escape(descriptions[name])}</text>',
            ])
            if stored:
                lines.append(f'<text x="{x + 12}" y="{y + 63}" class="kind">'
                             'SOURCE TABLE · stores rows</text>')
            else:
                read_lines = []
                current = 'Reads: '
                for parent in dependencies[name]:
                    candidate = current + (', ' if current != 'Reads: ' else '') + parent
                    if len(candidate) > 44 and current != 'Reads: ':
                        read_lines.append(current)
                        current = parent
                    else:
                        current = candidate
                read_lines.append(current)
                if len(read_lines) > 3:
                    raise ValueError(f'Too many input lines for {name}')
                for line_index, value in enumerate(read_lines):
                    lines.append(f'<text x="{x + 12}" y="{y + 63 + 13 * line_index}" '
                                 f'class="reads">{escape(value)}</text>')
            lines.append('</g>')
    lines.append('<text x="28" y="616" class="note">Green = stored source table · White = calculated SQL view · Views run on query and do not copy rows</text>')
    lines.append('</svg>')
    return '\n'.join(lines)


def render_svg(tables, relationships):
    """Keep connectors in the gutters, with the inference path down the middle."""
    card_width = 320
    columns = {
        table['name']: table['columns']
        for table in tables
    }
    row_heights = [max(100 + len(columns[name]) * 24
                       for name, (_, y) in GRID.items() if y == row)
                   for row in range(max(y for _, y in GRID.values()) + 1)]
    row_tops = [64]
    for height in row_heights[:-1]:
        row_tops.append(row_tops[-1] + height + 104)
    positions = {name: (40 + x * 400, row_tops[y]) for name, (x, y) in GRID.items()}
    heights = {name: row_heights[row] for name, (_, row) in GRID.items()}
    canvas_height = row_tops[-1] + row_heights[-1] + 60
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{canvas_height}" viewBox="0 0 1200 {canvas_height}" role="img" aria-labelledby="title desc">',
           '<title id="title">OrgGraph database entity relationship diagram</title>',
           '<desc id="desc">The two persisted source tables and their columns. Inference and metrics are calculated by SQL views.</desc>',
           '<rect width="1200" height="100%" fill="#fafbf8"/>',
           '<style>text{font-family:system-ui,sans-serif;fill:#283c32}.field{font-family:ui-monospace,monospace;font-size:12px}.key{font-family:ui-monospace,monospace;font-size:10px;fill:#4c624e}.edge{font-size:12px;font-weight:600;paint-order:stroke;stroke:#fafbf8;stroke-width:6px;stroke-linejoin:round}.note{font-size:12px;fill:#5c6c5e}</style>',
           '<text x="40" y="30" class="note">PK  Primary key     FK  Foreign key     Each line represents one foreign-key constraint</text>']

    def cardinality(x, y, dx, dy, kind):
        # dx/dy points from the table boundary into the connector.
        def line(a, b, c, d):
            return f'<path d="M{a},{b} L{c},{d}" stroke="#526d5a" stroke-width="1.5" fill="none"/>'

        def bar(distance):
            bx, by = x + dx * distance, y + dy * distance
            return line(bx - dy * 6, by + dx * 6, bx + dy * 6, by - dx * 6)

        marks = []
        if kind == 'one':
            marks.extend([bar(7), bar(14)])
        else:
            distance = 23 if kind == 'many' else 17
            marks.append(f'<circle cx="{x+dx*distance}" cy="{y+dy*distance}" r="4" fill="#fafbf8" stroke="#526d5a" stroke-width="1.5"/>')
            if kind == 'many':
                for side in [-1, 0, 1]:
                    marks.append(line(x + dx * 13, y + dy * 13,
                                      x + dx * 2 - dy * side * 7,
                                      y + dy * 2 + dx * side * 7))
            else:
                marks.append(bar(7))
        return ''.join(marks)

    groups = defaultdict(list)
    for relation in relationships:
        groups[(relation['parent'], relation['child'])].append(relation)
    for (parent, child), references in groups.items():
        px, py = positions[parent]
        cx, cy = positions[child]
        for index, relation in enumerate(references):
            if py == cy:
                x1 = px + card_width if px < cx else px
                x2 = cx if px < cx else cx + card_width
                y1 = y2 = py + 92 + index * 48
                path = f'M{x1},{y1} H{x2}'
                direction = 1 if px < cx else -1
                start_direction, end_direction = (direction, 0), (-direction, 0)
            else:
                x1 = px + card_width / 2
                x2 = cx + card_width / 2
                y1 = py + heights[parent] if py < cy else py
                y2 = cy if py < cy else cy + heights[child]
                bend = (y1 + y2) / 2
                path = f'M{x1},{y1} V{bend} H{x2} V{y2}'
                direction = 1 if py < cy else -1
                start_direction, end_direction = (0, direction), (0, -direction)
            dash = '' if relation['identifying'] else ' stroke-dasharray="5 3"'
            svg.append(f'<path d="{path}" stroke="#718776" stroke-width="1.5" fill="none"{dash}/>')
            svg.append(cardinality(x1, y1, *start_direction,
                                   'optional_one' if relation['optional'] else 'one'))
            svg.append(cardinality(x2, y2, *end_direction,
                                   'optional_one' if relation['cardinality'] == '0..1' else 'many'))

    for table in tables:
        name = table['name']
        x, y = positions[name]
        height = heights[name]
        svg.extend([
            f'<g aria-label="{name}">',
            f'<rect x="{x}" y="{y}" width="{card_width}" height="{height}" rx="6" fill="white" stroke="#b9c8b9"/>',
            f'<path d="M{x},{y+62} H{x+card_width}" stroke="#e1e8dd"/>',
            f'<text x="{x+16}" y="{y+26}" font-size="17" font-weight="650">{name}</text>',
            f'<text x="{x+16}" y="{y+47}" class="note">{escape(table["grain"])}</text>',
        ])
        for index, column in enumerate(columns[name]):
            keys = ','.join(label for label, condition in [('PK', column['pk']), ('FK', column['fk'])] if condition)
            baseline = y + 85 + index * 24
            svg.extend([
                f'<text x="{x+16}" y="{baseline}" class="key">{keys}</text>',
                f'<text x="{x+64}" y="{baseline}" class="field">{escape(column["name"])}</text>',
                f'<text x="{x+card_width-14}" y="{baseline}" text-anchor="end" class="key">{column["type"]}</text>',
            ])
        count = len(table['columns'])
        footer = f'{count} columns'
        svg.append(f'<text x="{x+16}" y="{y+height-13}" class="note">{footer}</text></g>')
    svg.append(f'<text x="40" y="{canvas_height-20}" class="note">Circle = optional · bar = one · fork = many. Solid = identifying relationship · dashed = non-identifying.</text></svg>')
    return '\n'.join(svg)


def build_diagram():
    connection = sqlite3.connect(':memory:')
    connection.executescript((ROOT / 'schema.sql').read_text())
    tables = []
    relationships = []
    for name in GRID:
        columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        groups = defaultdict(list)
        for row in connection.execute(f'PRAGMA foreign_key_list("{name}")'):
            groups[row[0]].append(row)
        keys = [row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5]]
        foreign_columns = {row[3] for group in groups.values() for row in group}
        tables.append({'name': name, 'grain': GRAINS[name], 'columns': [
            {'name': row[1], 'type': row[2], 'required': bool(row[3]),
             'pk': row[5], 'fk': row[1] in foreign_columns} for row in columns]})
        for group in groups.values():
            group.sort(key=lambda row: row[1])
            child_columns = [row[3] for row in group]
            relationships.append({
                'parent': group[0][2], 'child': name,
                'parent_columns': [row[4] for row in group], 'child_columns': child_columns,
                'cardinality': '0..1' if set(child_columns) == set(keys) else '0..many',
                'optional': any(not row[3] for row in columns if row[1] in child_columns),
                'identifying': set(child_columns).issubset(keys),
            })
    views = []
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY rowid"):
        grain = VIEW_GRAINS.get(name, 'Calculated from source and other views')
        columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'view' AND name = ?", (name,)
        ).fetchone()[0]
        views.append({
            'name': name,
            'grain': grain,
            'definition': definition + ';',
            'columns': [
                {'name': row[1], 'type': row[2], 'required': bool(row[3]),
                 'pk': row[5], 'fk': False} for row in columns
            ],
        })
    connection.close()
    dependencies = view_dependencies(tables, views)
    for view in views:
        view['reads'] = dependencies[view['name']]
    (ROOT / 'public/database-erd.svg').write_text(render_svg(tables, relationships))
    (ROOT / 'public/database-erd-full.svg').write_text(render_svg(tables, relationships))
    (ROOT / 'public/database-view-flow.svg').write_text(
        render_view_flow(tables, views, dependencies))
    metadata = {
        'tables': tables, 'views': views, 'relationships': relationships,
        'company_query': (ROOT / 'sql/company_predictions.sql').read_text(),
    }
    (ROOT / 'public/database-schema.json').write_text(json.dumps(metadata, indent=2))
    mermaid = ['erDiagram']
    for table in tables:
        mermaid.append(f'    {table["name"]} {{')
        for column in table['columns']:
            keys = ','.join(label for label, condition in [('PK', column['pk']), ('FK', column['fk'])] if condition)
            mermaid.append(f'        {column["type"]} {column["name"]} {keys}'.rstrip())
        mermaid.append('    }')
    for relation in relationships:
        many = 'o|' if relation['cardinality'] == '0..1' else 'o{'
        parent = '|o' if relation['optional'] else '||'
        label = relation['child_columns'][-1]
        line = '--' if relation['identifying'] else '..'
        mermaid.append(f'    {relation["parent"]} {parent}{line}{many} {relation["child"]} : {label}')
    (ROOT / 'public/database-erd.mmd').write_text('\n'.join(mermaid) + '\n')


if __name__ == '__main__':
    build_diagram()
