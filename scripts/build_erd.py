"""Build the portal's schema diagram from SQLite's own key definitions."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
GRID = {
    'companies': (0, 0), 'employees': (0, 1), 'benchmark_labels': (1, 1),
    'inference_runs': (2, 0), 'inference_outputs': (2, 1),
}
GRAINS = {
    'companies': 'One company', 'employees': 'One observed employee',
    'benchmark_labels': 'One generated source label per employee',
    'inference_runs': 'One checked source/model run',
    'inference_outputs': 'One durable model decision per employee/run',
}
VIEW_GRAINS = {
    'benchmark_truth': 'One answer derived from source labels',
    'benchmark_comparison': 'One live prediction-versus-label comparison',
    'company_profiles': 'One live company profile',
    'employee_features': 'One employee feature set per ready run',
    'reporting_predictions': 'One current decision per employee/ready run',
    'prediction_reasons': 'One explanation signal per decision',
    'employee_noise': 'One generated noise label per employee',
    'company_run_metrics': 'One calculated company summary per ready run',
    'run_metrics': 'One calculated summary per ready run',
    'employee_reporting_audit': 'One inspectable decision per employee/ready run',
}


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
           '<desc id="desc">All columns and SQL types in five persisted tables. PK marks primary keys and FK marks foreign keys. Derived views are documented separately.</desc>',
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
    for name, grain in VIEW_GRAINS.items():
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
    (ROOT / 'public/database-erd.svg').write_text(render_svg(tables, relationships))
    (ROOT / 'public/database-erd-full.svg').write_text(render_svg(tables, relationships))
    metadata = {'tables': tables, 'views': views, 'relationships': relationships}
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
