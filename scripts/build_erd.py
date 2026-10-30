"""Build the portal's schema diagram from SQLite's own key definitions."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
GRID = {
    'companies': (0, 1), 'employees': (1, 0), 'benchmark_truth': (0, 0),
    'inference_runs': (1, 2), 'employee_features': (1, 1),
    'reporting_predictions': (2, 1), 'company_run_metrics': (0, 2),
    'employee_noise': (2, 0), 'prediction_reasons': (2, 2),
}
GRAINS = {
    'companies': 'One company', 'employees': 'One observed employee',
    'benchmark_truth': 'One generated answer per employee',
    'inference_runs': 'One checked source/model run',
    'employee_features': 'One employee per run',
    'reporting_predictions': 'One reporting decision per employee/run',
    'company_run_metrics': 'One company summary per run',
    'employee_noise': 'One noise label per employee/position',
    'prediction_reasons': 'One signal per decision/position',
}


def render_svg(tables, relationships, *, all_columns=False):
    """Keep connectors in the gutters, with the inference path down the middle."""
    card_width = 320
    columns = {
        table['name']: [column for column in table['columns']
                        if all_columns or column['pk'] or column['fk']]
        for table in tables
    }
    row_heights = [max(100 + len(columns[name]) * 24
                       for name, (_, y) in GRID.items() if y == row)
                   for row in range(3)]
    row_tops = [64]
    for height in row_heights[:-1]:
        row_tops.append(row_tops[-1] + height + 104)
    positions = {name: (40 + x * 400, row_tops[y]) for name, (x, y) in GRID.items()}
    heights = {name: row_heights[row] for name, (_, row) in GRID.items()}
    canvas_height = row_tops[-1] + row_heights[-1] + 60
    title = 'All columns' if all_columns else 'Keys and relationships'
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{canvas_height}" viewBox="0 0 1200 {canvas_height}" role="img" aria-labelledby="title desc">',
           f'<title id="title">OrgGraph entity relationship diagram — {title}</title>',
           '<desc id="desc">Nine tables with non-overlapping connections. Arrows point from referenced to dependent tables. R1 through R12 identify the complete foreign keys listed in the portal.</desc>',
           '<rect width="1200" height="100%" fill="#fafbf8"/>',
           '<style>text{font-family:system-ui,sans-serif;fill:#283c32}.field{font-family:ui-monospace,monospace;font-size:13px}.key{font-family:ui-monospace,monospace;font-size:10px;fill:#4c624e}.edge{font-size:12px;font-weight:600;paint-order:stroke;stroke:#fafbf8;stroke-width:6px;stroke-linejoin:round}.note{font-size:12px;fill:#5c6c5e}</style>',
           '<defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0,0 L7,3.5 L0,7" fill="#718776"/></marker></defs>',
           '<text x="40" y="30" class="note">PK  Primary key     FK  Foreign key     Arrow  Referenced → dependent table</text>']

    edges = defaultdict(list)
    for relation in relationships:
        edges[(relation['parent'], relation['child'])].append(relation['id'])
    for (parent, child), labels in edges.items():
        px, py = positions[parent]
        cx, cy = positions[child]
        if parent == 'companies' and child == 'employees':
            # Enter the employee card to the left of its separate feature link.
            x1, y1 = px + card_width / 2, py
            x2, y2 = cx + 80, cy + heights[child]
            bend = py - 40
            path = f'M{x1},{y1} V{bend} H{x2} V{y2}'
            tx, ty = (x1 + x2) / 2, bend - 10
        elif py == cy:
            x1 = px + card_width if px < cx else px
            x2 = cx if px < cx else cx + card_width
            y = py + 92
            path = f'M{x1},{y} H{x2}'
            tx, ty = (x1 + x2) / 2, y - 12
        else:
            # Two distinct ports keep the employee and run references apart.
            offset = 240 if parent == 'employees' else card_width / 2
            x = px + offset
            y1 = py + heights[parent] if py < cy else py
            y2 = cy if py < cy else cy + heights[child]
            path = f'M{x},{y1} V{y2}'
            tx, ty = x + 24, (y1 + y2) / 2
        label = ', '.join(labels)
        svg.extend([
            f'<path d="{path}" stroke="#718776" stroke-width="1.5" fill="none" marker-end="url(#arrow)"/>',
            f'<text x="{tx}" y="{ty}" text-anchor="middle" class="edge">{escape(label)}</text>',
        ])

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
            ])
        count = len(table['columns'])
        footer = f'{count} columns' if all_columns else f'{count} columns · all attributes listed below'
        svg.append(f'<text x="{x+16}" y="{y+height-13}" class="note">{footer}</text></g>')
    svg.append(f'<text x="40" y="{canvas_height-20}" class="note">Parallel references share one connector. The relationship reference lists each composite key and its cardinality.</text></svg>')
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
                'id': f'R{len(relationships) + 1}', 'parent': group[0][2], 'child': name,
                'parent_columns': [row[4] for row in group], 'child_columns': child_columns,
                'cardinality': '0..1' if set(child_columns) == set(keys) else '0..many',
                'optional': any(not row[3] for row in columns if row[1] in child_columns),
            })
    connection.close()
    (ROOT / 'public/database-erd.svg').write_text(render_svg(tables, relationships))
    (ROOT / 'public/database-erd-full.svg').write_text(render_svg(tables, relationships, all_columns=True))
    metadata = {'tables': tables, 'relationships': relationships}
    (ROOT / 'public/database-schema.json').write_text(json.dumps(metadata, indent=2))
    mermaid = ['erDiagram']
    for table in tables:
        mermaid.append(f'    {table["name"]} {{')
        for column in table['columns']:
            keys = ','.join(label for label, condition in [('PK', column['pk']), ('FK', column['fk'])] if condition)
            mermaid.append(f'        {column["type"]} {column["name"]} {keys}')
        mermaid.append('    }')
    for relation in relationships:
        many = 'o|' if relation['cardinality'] == '0..1' else 'o{'
        mermaid.append(f'    {relation["parent"]} ||--{many} {relation["child"]} : {relation["id"]}')
    (ROOT / 'public/database-erd.mmd').write_text('\n'.join(mermaid) + '\n')


if __name__ == '__main__':
    build_diagram()
