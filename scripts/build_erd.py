"""Build the portal's schema diagram from SQLite's own key definitions."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
POSITIONS = {
    'companies': (35, 65), 'employees': (445, 65), 'benchmark_truth': (855, 65),
    'inference_runs': (35, 445), 'employee_features': (445, 445),
    'reporting_predictions': (855, 445), 'company_run_metrics': (35, 1010),
    'employee_noise': (445, 1010), 'prediction_reasons': (855, 1010),
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


def build_diagram():
    connection = sqlite3.connect(':memory:')
    connection.executescript((ROOT / 'schema.sql').read_text())
    tables = []
    relationships = []
    for name in POSITIONS:
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
    width = 360
    heights = {table['name']: 76 + len(table['columns']) * 23 for table in tables}
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1250" height="1410" viewBox="0 0 1250 1410" role="img" aria-labelledby="title desc">',
           '<title id="title">OrgGraph entity relationship diagram</title>',
           '<desc id="desc">Nine relational tables. PK marks primary keys and FK marks foreign keys. Relationship IDs match the key reference below the diagram.</desc>',
           '<rect width="1250" height="1410" fill="#f6f8f3"/>',
           '<defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="#829282"/></marker></defs>']
    # Bundle parallel relationships; the reference lists every composite key separately.
    edges = defaultdict(list)
    for relation in relationships:
        edges[(relation['parent'], relation['child'])].append(relation['id'])
    for (parent, child), labels in edges.items():
        px, py = POSITIONS[parent]
        cx, cy = POSITIONS[child]
        if py == cy and px < cx:
            x1, y1 = px + width, py + 40
            x2, y2 = cx, cy + 40
            path = f'M{x1},{y1} L{x2},{y2}'
            tx, ty = (x1 + x2) / 2, y1 - 9
        elif py == cy:
            # A long same-row link goes around the row, never through another table.
            bottom = max(y + heights[name] for name, (x, y) in POSITIONS.items() if y == py) + 24
            x1, y1 = px + width / 2, py + heights[parent]
            x2, y2 = cx + width, cy + 40
            path = f'M{x1},{y1} V{bottom} H1235 V{y2} H{x2}'
            tx, ty = (x1 + 1235) / 2, bottom - 8
        else:
            x1, y1 = px + width / 2, py + heights[parent]
            x2, y2 = cx + width / 2, cy
            gutter = px - 20
            path = f'M{x1},{y1} V{y1+16} H{gutter} V{y2-18} H{x2} V{y2}'
            tx, ty = gutter + 12, (y1 + y2) / 2
        svg.append(f'<path d="{path}" stroke="#829282" stroke-width="1.5" fill="none" marker-end="url(#arrow)"/>')
        svg.append(f'<text x="{tx}" y="{ty}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#426149">{escape(",".join(labels))}</text>')
    for table in tables:
        name = table['name']
        x, y = POSITIONS[name]
        svg.extend([
            f'<rect x="{x}" y="{y}" width="{width}" height="{heights[name]}" rx="6" fill="white" stroke="#cbd6c8"/>',
            f'<text x="{x+16}" y="{y+28}" font-family="sans-serif" font-size="18" font-weight="600" fill="#283c32">{name}</text>',
            f'<text x="{x+16}" y="{y+49}" font-family="sans-serif" font-size="11" fill="#637063">{escape(table["grain"])}</text>',
        ])
        for index, column in enumerate(table['columns']):
            keys = ','.join(label for label, condition in [('PK', column['pk']), ('FK', column['fk'])] if condition)
            label = f'{keys:5} {column["name"]}'
            svg.append(f'<text x="{x+16}" y="{y+77+index*23}" font-family="monospace" font-size="12" fill="#344439">{escape(label)}</text>')
    svg.append('<text x="35" y="1360" font-family="sans-serif" font-size="14" fill="#344439">Arrow: referenced table → dependent table. Full cardinality and composite keys are listed in the portal.</text>')
    svg.append('<text x="35" y="1385" font-family="sans-serif" font-size="13" fill="#637063">employee_reporting_audit is a read-only view over raw records, features, predictions and run metadata.</text></svg>')
    (ROOT / 'public/database-erd.svg').write_text('\n'.join(svg))
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
