"""Read SQLite's schema and draw its tables, views and direct connections."""

from collections import defaultdict
from html import escape
import json
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
GRAINS = {
    'companies': 'Company details',
    'employees': 'Original employee records',
    'inference_settings': 'Decision thresholds',
    'company_profiles': 'Company size and headcount',
    'employee_text': 'Title and team text, cleaned for matching',
    'employee_classification': 'Department and seniority from the title',
    'employee_features': 'Employee attributes used for matching',
    'manager_candidates': 'Possible managers in the same company',
    'candidate_scores': 'Evidence for each possible manager',
    'employee_top_candidates': 'The best two candidates',
    'reporting_predictions': 'Accepted or unresolved manager',
    'prediction_reasons': 'Why a decision was made',
    'company_metrics': 'Reporting coverage by company',
    'dataset_metrics': 'Totals across the database',
    'employee_reporting_audit': 'Employee, manager and decision details',
}


def view_dependencies(tables, views):
    names = {item['name'] for item in [*tables, *views]}
    result = {}
    for view in views:
        references = re.findall(r'\b(?:FROM|JOIN)\s+"?([A-Za-z_][A-Za-z_0-9]*)',
                                view['definition'], flags=re.IGNORECASE)
        result[view['name']] = [name for name in dict.fromkeys(references)
                                if name in names and name != view['name']]
    return result


def render_svg(tables, views, relationships, dependencies):
    objects = {item['name']: item for item in [*tables, *views]}
    edges = [(r['parent'], r['child'], 'foreign-key') for r in relationships]
    edges += [(parent, child, 'view-input') for child, parents in dependencies.items()
              for parent in parents]
    parents = defaultdict(list)
    for parent, child, _ in edges:
        parents[child].append(parent)
    levels = {}

    def level(name, visiting=None):
        if name in levels:
            return levels[name]
        visiting = set() if visiting is None else visiting
        if name in visiting:
            raise ValueError(f'Circular schema dependency: {name}')
        depth = 1 + max((level(parent, visiting | {name})
                         for parent in parents[name]), default=-1)
        levels[name] = depth
        return depth

    rows = defaultdict(list)
    for name in objects:
        rows[level(name)].append(name)
    card_width, column_gap, row_gap = 390, 95, 100
    heights = {name: 96 + 23 * len(item['columns']) for name, item in objects.items()}
    row_widths = {row: len(names) * card_width + (len(names) - 1) * column_gap
                  for row, names in rows.items()}
    content_width = max(row_widths.values())
    # Long dependencies use their own lanes outside the cards. Adjacent rows
    # connect through the gap between rows rather than through another object.
    long_edges = [(a, b) for a, b, _ in edges if levels[b] > levels[a] + 1]
    side_width = 65 + 13 * ((len(long_edges) + 1) // 2)
    canvas_width = content_width + side_width * 2
    positions = {}
    y = 100
    for row, names in sorted(rows.items()):
        x = (canvas_width - row_widths[row]) / 2
        for name in names:
            positions[name] = (x, y)
            x += card_width + column_gap
        y += max(heights[name] for name in names) + row_gap
    canvas_height = y - row_gap + 65
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{canvas_width}" height="{canvas_height}" viewBox="0 0 {canvas_width} {canvas_height}" role="img" aria-labelledby="title desc">',
        '<title id="title">OrgGraph tables and views</title>',
        '<desc id="desc">Every stored table and SQL view, with all columns. Solid green connects a foreign key. Dashed blue arrows show a view reading a table or another view. Select an object to highlight its direct inputs and outputs.</desc>',
        '<style>text{font-family:Arial,sans-serif;fill:#263b34}.name{font-size:17px;font-weight:700}.column{font-family:monospace;font-size:12px}.type{font-family:monospace;font-size:10px;fill:#66756c}.note{font-size:12px;fill:#627168}.kind{font-size:10px;font-weight:700}.entity{cursor:pointer;outline:none}.entity:focus rect{stroke:#164d82;stroke-width:3}.entity.is-muted,.edge.is-muted{opacity:.09}.entity.is-selected rect{stroke:#164d82;stroke-width:3}.edge.is-related{stroke:#164d82;stroke-width:2.4}</style>',
        f'<rect width="{canvas_width}" height="{canvas_height}" fill="#fafbf8"/>',
        '<defs><marker id="read-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#69849b"/></marker></defs>',
        '<text x="32" y="30" class="name">Tables and views</text>',
        '<text x="32" y="54" class="note">Green = stored table · Blue = calculated view · PK = primary key · FK = foreign key</text>',
        '<text x="32" y="75" class="note">Solid line = foreign key · Dashed arrow = reads from · Select a card to follow its connections</text>',
    ]
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for edge in edges:
        outgoing[edge[0]].append(edge)
        incoming[edge[1]].append(edge)
    for name in objects:
        outgoing[name].sort(key=lambda edge: (levels[edge[1]], positions[edge[1]][0]))
        incoming[name].sort(key=lambda edge: (levels[edge[0]], positions[edge[0]][0]))
    for parent, child, kind in edges:
        edge = parent, child, kind
        px, py = positions[parent]
        cx, cy = positions[child]
        sx = px + card_width * (outgoing[parent].index(edge) + 1) / (len(outgoing[parent]) + 1)
        ex = cx + card_width * (incoming[child].index(edge) + 1) / (len(incoming[child]) + 1)
        sy = py + heights[parent]
        if (parent, child) in long_edges:
            index = long_edges.index((parent, child))
            lane = side_width - 30 - 13 * (index // 2) if index % 2 == 0 else canvas_width - side_width + 30 + 13 * (index // 2)
            path = f'M{sx},{sy} V{sy+22} H{lane} V{cy-24} H{ex} V{cy}'
        else:
            middle = cy - 45 - 5 * (incoming[child].index(edge) % 5)
            path = f'M{sx},{sy} V{middle} H{ex} V{cy}'
        style = 'stroke="#64816b"' if kind == 'foreign-key' else 'stroke="#8b9eaf" stroke-dasharray="5 4" marker-end="url(#read-arrow)"'
        title = f'{child} references {parent}' if kind == 'foreign-key' else f'{child} reads {parent}'
        lines.append(f'<path class="edge" data-parent="{parent}" data-child="{child}" data-kind="{kind}" d="{path}" {style} stroke-width="1.4" fill="none"><title>{escape(title)}</title></path>')
        if kind == 'foreign-key':
            lines.append(f'<g class="edge" data-parent="{parent}" data-child="{child}"><path d="M{sx-6},{sy+7} H{sx+6} M{sx-6},{sy+14} H{sx+6} M{ex},{cy-14} L{ex-7},{cy-2} M{ex},{cy-14} V{cy-2} M{ex},{cy-14} L{ex+7},{cy-2}" fill="none" stroke="#64816b" stroke-width="1.4"/><circle cx="{ex}" cy="{cy-24}" r="4" fill="#fafbf8" stroke="#64816b"/></g>')
    for name, item in objects.items():
        x, y = positions[name]
        stored = item['kind'] == 'table'
        fill, stroke = ('#eaf2e8', '#8aa58b') if stored else ('#edf3f8', '#91a7b9')
        lines += [
            f'<g class="entity" id="{name}" data-name="{name}" data-kind="{item["kind"]}" tabindex="0" role="button" aria-label="{name}, {item["kind"]}">',
            f'<rect x="{x}" y="{y}" width="{card_width}" height="{heights[name]}" rx="6" fill="white" stroke="{stroke}"/>',
            f'<path d="M{x+1} {y+65} H{x+card_width-1} V{y+6} Q{x+card_width-1} {y+1} {x+card_width-6} {y+1} H{x+6} Q{x+1} {y+1} {x+1} {y+6} Z" fill="{fill}"/>',
            f'<text x="{x+14}" y="{y+17}" class="kind">{"TABLE" if stored else "VIEW"}</text>',
            f'<text x="{x+14}" y="{y+39}" class="name">{name}</text>',
            f'<text x="{x+14}" y="{y+57}" class="note">{escape(item["grain"])}</text>',
        ]
        for index, column in enumerate(item['columns']):
            baseline = y + 88 + index * 23
            keys = ','.join(key for key, active in [('PK', column['pk']), ('FK', column['fk'])] if active)
            lines += [
                f'<text x="{x+14}" y="{baseline}" class="type">{keys}</text>',
                f'<text x="{x+62}" y="{baseline}" class="column">{column["name"]}</text>',
                f'<text x="{x+card_width-12}" y="{baseline}" text-anchor="end" class="type">{column["type"] or "derived"}</text>',
            ]
        lines.append('</g>')
    lines.append(f'<text x="32" y="{canvas_height-22}" class="note">Views store no rows. Arrows show direct SQL dependencies, not foreign-key constraints.</text>')
    lines.append('''<script><![CDATA[
function selectObject(name) {
  const entities = [...document.querySelectorAll('.entity')];
  const edges = [...document.querySelectorAll('.edge')];
  const related = new Set([name]);
  for (const edge of edges) {
    const active = edge.dataset.parent === name || edge.dataset.child === name;
    if (active) { related.add(edge.dataset.parent); related.add(edge.dataset.child); }
    edge.classList.toggle('is-related', !!name && active);
    edge.classList.toggle('is-muted', !!name && !active);
  }
  for (const entity of entities) {
    entity.classList.toggle('is-selected', entity.dataset.name === name);
    entity.classList.toggle('is-muted', !!name && !related.has(entity.dataset.name));
  }
}
for (const entity of document.querySelectorAll('.entity')) {
  entity.addEventListener('click', () => selectObject(entity.classList.contains('is-selected') ? null : entity.dataset.name));
  entity.addEventListener('keydown', event => {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectObject(entity.dataset.name); }
    if (event.key === 'Escape') selectObject(null);
  });
}
document.addEventListener('click', event => { if (!event.target.closest('.entity')) selectObject(null); });
]]></script></svg>''')
    return '\n'.join(lines)


def build_diagram():
    connection = sqlite3.connect(':memory:')
    connection.executescript((ROOT / 'schema.sql').read_text())
    tables, views, relationships = [], [], []
    objects = connection.execute("SELECT name, type, sql FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY rowid").fetchall()
    for name, kind, definition in objects:
        columns = connection.execute(f'PRAGMA table_info("{name}")').fetchall()
        groups = defaultdict(list)
        for row in connection.execute(f'PRAGMA foreign_key_list("{name}")'):
            groups[row[0]].append(row)
        foreign_columns = {row[3] for group in groups.values() for row in group}
        item = {'name': name, 'kind': kind, 'grain': GRAINS.get(name, name.replace('_', ' ')),
                'columns': [{'name': row[1], 'type': row[2], 'required': bool(row[3]),
                             'pk': row[5], 'fk': row[1] in foreign_columns} for row in columns]}
        if kind == 'view':
            item['definition'] = definition + ';'
            views.append(item)
        else:
            tables.append(item)
        keys = [row[1] for row in columns if row[5]]
        for group in groups.values():
            group.sort(key=lambda row: row[1])
            child_columns = [row[3] for row in group]
            relationships.append({'parent': group[0][2], 'child': name,
                                  'parent_columns': [row[4] for row in group], 'child_columns': child_columns,
                                  'cardinality': '0..1' if set(child_columns) == set(keys) else '0..many',
                                  'optional': any(not row[3] for row in columns if row[1] in child_columns),
                                  'identifying': set(child_columns).issubset(keys)})
    connection.close()
    dependencies = view_dependencies(tables, views)
    for view in views:
        view['reads'] = dependencies[view['name']]
    svg = render_svg(tables, views, relationships, dependencies)
    for name in ['database-erd.svg', 'database-erd-full.svg', 'database-view-flow.svg']:
        (ROOT / 'public' / name).write_text(svg)
    metadata = {'tables': tables, 'views': views, 'relationships': relationships,
                'company_query': (ROOT / 'sql/company_predictions.sql').read_text(),
                'diagram': dict(zip(['width', 'height'], re.search(r'width="(\d+)" height="(\d+)"', svg).groups()))}
    (ROOT / 'public/database-schema.json').write_text(json.dumps(metadata, indent=2))
    mermaid = ['flowchart TB']
    for item in [*tables, *views]:
        label = item['name'] + '<br/>' + item['kind'].upper() + '<br/>'
        label += '<br/>'.join(column['name'] + ' : ' + (column['type'] or 'derived') for column in item['columns'])
        mermaid.append(f'    {item["name"]}["{label}"]')
    for relationship in relationships:
        mermaid.append(f'    {relationship["parent"]} -->|company_id FK| {relationship["child"]}')
    for name, inputs in dependencies.items():
        for source in inputs:
            mermaid.append(f'    {source} -.-> {name}')
    (ROOT / 'public/database-erd.mmd').write_text('\n'.join(mermaid) + '\n')


if __name__ == '__main__':
    build_diagram()
