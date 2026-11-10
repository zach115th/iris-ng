#  IRIS Source Code
#  Copyright (C) 2024 - DFIR-IRIS
#  contact@dfir-iris.org
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 3 of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import itertools
from datetime import datetime
from html import escape
from flask_login import current_user
from flask import Blueprint

from app.datamgmt.case.case_events_db import get_case_events_assets_graph
from app.datamgmt.case.case_events_db import get_case_events_ioc_graph
from app.datamgmt.case.case_graph_db import get_case_evidence_asset_links
from app.datamgmt.case.case_graph_db import get_case_graph_assets
from app.datamgmt.case.case_graph_db import get_case_ioc_asset_links
from app.datamgmt.case.case_graph_db import get_case_note_ioc_links
from app.datamgmt.case.case_graph_db import get_case_open_vulnerability_findings
from app.models import vulnerability_vocab as vv
from app.models.authorization import CaseAccessLevel
from app.blueprints.access_controls import ac_requires_case_identifier
from app.blueprints.access_controls import ac_api_requires
from app.blueprints.responses import response_success

case_graph_rest_blueprint = Blueprint('case_graph_rest', __name__)


@case_graph_rest_blueprint.route('/case/graph/getdata', methods=['GET'])
@ac_requires_case_identifier(CaseAccessLevel.read_only, CaseAccessLevel.full_access)
@ac_api_requires()
def case_graph_get_data(caseid):
    events = get_case_events_assets_graph(caseid)
    events.extend(get_case_events_ioc_graph(caseid))

    nodes = []
    edges = []
    dates = {
        "human": [],
        "machine": []
    }

    tmp = {}
    for event in events:
        if hasattr(event, 'asset_compromise_status_id'):
            if event.asset_compromise_status_id == 1:
                img = event.asset_icon_compromised

            else:
                img = event.asset_icon_not_compromised

            if event.asset_ip:
                title = "{} -{}".format(event.asset_ip, event.asset_description)
            else:
                title = "{}".format(event.asset_description)
            label = event.asset_name
            idx = f'a{event.asset_id}'
            node_type = 'asset'

        else:
            img = 'virus-covid-solid.png'
            label = event.ioc_value
            title = event.ioc_description
            idx = f'b{event.ioc_id}'
            node_type = 'ioc'

        try:
            date = "{}-{}-{}".format(event.event_date.day, event.event_date.month, event.event_date.year)
        except:
            date = '15-05-2021'

        if date not in dates:
            dates['human'].append(date)
            dates['machine'].append(datetime.timestamp(event.event_date))

        new_node = {
            'id': idx,
            'label': label,
            'image': '/static/assets/img/graph/' + img,
            'shape': 'image',
            'title': title,
            'value': 1,
            # iris-next: layer tag drives the Graph tab's knowledge-map filter.
            'layer': node_type
        }

        # iris-ng: dark is the only theme (issue #92) — labels are always white.
        new_node['font'] = "12px verdana white"

        if not any(node['id'] == idx for node in nodes):
            nodes.append(new_node)

        ak = {
            'node_id': idx,
            'node_title': "{} - {}".format(event.event_date, event.event_title),
            'node_name': label,
            'node_type': node_type
        }
        if tmp.get(event.event_id):
            tmp[event.event_id]['list'].append(ak)

        else:
            tmp[event.event_id] = {
                'master_node': [],
                'list': [ak]
            }

    for event_id in tmp:
        for subset in itertools.combinations(tmp[event_id]['list'], 2):

            if subset[0]['node_type'] == 'ioc' and subset[1]['node_type'] == 'ioc' and len(tmp[event_id]['list']) != 2:
                continue

            edge = {
                'from': subset[0]['node_id'],
                'to': subset[1]['node_id'],
                'title': subset[0]['node_title'],
                'dashes': subset[0]['node_type'] == 'ioc' or subset[1]['node_type'] == 'ioc',
                # iris-next: 'event' edges come from timeline co-occurrence.
                'kind': 'event'
            }
            edges.append(edge)

    # ------------------------------------------------------------------
    # iris-next knowledge-map overlay
    #
    # Everything above derives edges from timeline-event co-occurrence. The
    # layers below add the *direct* relationships stored in the M2M link
    # tables, plus note/evidence nodes, so the Graph tab can show provenance
    # ("which note produced this IOC?") and links no event happens to cover.
    #
    # Notes and evidence are only emitted when they actually have a link --
    # isolated nodes would just be floating noise on the canvas.
    # ------------------------------------------------------------------
    existing_ids = {node['id'] for node in nodes}
    # Pairs already joined by an event-derived edge. A direct link between the
    # same two nodes would render as a second parallel line saying nothing new,
    # so those are suppressed below.
    connected_pairs = {frozenset((e['from'], e['to'])) for e in edges}

    def _add_node(node):
        if node['id'] not in existing_ids:
            existing_ids.add(node['id'])
            nodes.append(node)

    font_colour = 'white'  # iris-ng: dark is the only theme (issue #92)

    # --- Notes (violet) linked to the IOCs they sourced ---
    for note_id, note_title, ioc_id, ioc_value in get_case_note_ioc_links(caseid):
        note_idx = f'n{note_id}'
        ioc_idx = f'b{ioc_id}'
        _add_node({
            'id': note_idx,
            'label': note_title or f'Note #{note_id}',
            'shape': 'box',
            'title': f'Note: {note_title}',
            'value': 1,
            'layer': 'note',
            'color': {'background': '#2a1f3d', 'border': '#8b5cf6'},
            'font': {'color': font_colour, 'size': 12}
        })
        # Only draw the edge if the IOC is actually on the canvas; an IOC that
        # is on no timeline event has no node here.
        if ioc_idx in existing_ids:
            edges.append({
                'from': note_idx,
                'to': ioc_idx,
                'title': f'{note_title} -> {ioc_value} (source note)',
                'dashes': True,
                'color': {'color': '#8b5cf6'},
                'kind': 'direct'
            })

    # --- Evidence (amber) linked to the assets it was collected from ---
    for evidence_id, filename, asset_id, asset_name in get_case_evidence_asset_links(caseid):
        ev_idx = f'e{evidence_id}'
        asset_idx = f'a{asset_id}'
        _add_node({
            'id': ev_idx,
            'label': filename or f'Evidence #{evidence_id}',
            'shape': 'box',
            'title': f'Evidence: {filename}',
            'value': 1,
            'layer': 'evidence',
            'color': {'background': '#3a2f1a', 'border': '#f4c430'},
            'font': {'color': font_colour, 'size': 12}
        })
        if asset_idx in existing_ids:
            edges.append({
                'from': ev_idx,
                'to': asset_idx,
                'title': f'{filename} <- {asset_name} (evidence)',
                'dashes': True,
                'color': {'color': '#f4c430'},
                'kind': 'direct'
            })

    # --- Direct IOC <-> asset links (not necessarily on any shared event) ---
    for ioc_id, ioc_value, asset_id, asset_name in get_case_ioc_asset_links(caseid):
        ioc_idx = f'b{ioc_id}'
        asset_idx = f'a{asset_id}'
        if ioc_idx not in existing_ids or asset_idx not in existing_ids:
            continue
        pair = frozenset((ioc_idx, asset_idx))
        if pair in connected_pairs:
            # Already joined by a timeline event -- don't double the line.
            continue
        connected_pairs.add(pair)
        edges.append({
            'from': ioc_idx,
            'to': asset_idx,
            'title': f'{ioc_value} <-> {asset_name} (direct link)',
            'dashes': True,
            'color': {'color': '#64748b'},
            'kind': 'direct'
        })

    _add_vulnerability_layer(caseid, nodes, edges, existing_ids, _add_node)

    resp = {
        'nodes': nodes,
        'edges': edges,
        'dates': dates
    }

    return response_success("", data=resp)


# iris-ng 2026-11-10: the Vulnerabilities layer (maintainer: open findings only, every kind of catalogue entry,
# coloured by the entry's severity; an affected asset on no graph event joins the map while the layer is on).
# vis.js 4.21 puts a node's or an edge's `title` into the tooltip as HTML, so every title written here is escaped.
VULN_COLOURS = {
    'critical': ('#f5365c', '#3d1a22'),
    'high': ('#fb6340', '#3d2418'),
    'medium': ('#f4c430', '#3a2f1a'),
    'low': ('#36a2eb', '#18283a'),
    'none': ('#9a9aa5', '#26262e'),
    'unknown': ('#9a9aa5', '#26262e'),
}


def _asset_tooltip(asset_ip, asset_description):
    """The asset tooltip of the event-derived nodes, escaped."""
    if asset_ip:
        return escape("{} -{}".format(asset_ip, asset_description))
    return escape("{}".format(asset_description))


def _add_vulnerability_layer(caseid, nodes, edges, existing_ids, add_node):
    findings = get_case_open_vulnerability_findings(caseid)
    if not findings:
        return
    missing = {row.asset_id for row in findings if f'a{row.asset_id}' not in existing_ids}
    for a in get_case_graph_assets(caseid, missing):
        img = a.asset_icon_compromised if a.asset_compromise_status_id == 1 else a.asset_icon_not_compromised
        add_node({
            'id': f'a{a.asset_id}',
            'label': a.asset_name,
            'image': '/static/assets/img/graph/' + img,
            'shape': 'image',
            'title': _asset_tooltip(a.asset_ip, a.asset_description),
            'value': 1,
            'layer': 'asset',
            # On no graph event: drawn only while the Vulnerabilities layer is on (case.graph.js).
            'only_with': 'vulnerability',
            'font': "12px verdana white",
        })

    by_vuln = {}
    for row in findings:
        by_vuln.setdefault(row.vulnerability_id, []).append(row)
    for vid, rows in by_vuln.items():
        first = rows[0]
        severity = first.severity if first.severity in VULN_COLOURS else 'unknown'
        border, background = VULN_COLOURS[severity]
        per_asset = {}
        for row in rows:
            per_asset.setdefault(row.asset_id, (row.asset_name, []))[1].append(row.remediation_status)
        score = ' %.1f' % first.cvss_score if first.cvss_score is not None else ''
        node_id = f'v{vid}'
        add_node({
            'id': node_id,
            'label': first.identifier,
            'shape': 'ellipse',
            'title': '%s<br>%s%s - %s<br>%s<br>Open on %d asset%s' % (
                escape(first.identifier), escape(vv.SEVERITY_LABELS.get(severity, severity)), escape(score),
                escape(vv.KIND_LABELS.get(first.kind, first.kind)), escape(first.title),
                len(per_asset), '' if len(per_asset) == 1 else 's'),
            'value': 1,
            'layer': 'vulnerability',
            'severity': severity,
            'color': {'background': background, 'border': border,
                      'highlight': {'background': background, 'border': '#ffffff'}},
            'borderWidth': 2,
            'font': {'color': 'white', 'size': 12},
        })
        for asset_id, (asset_name, statuses) in sorted(per_asset.items()):
            asset_node = f'a{asset_id}'
            if asset_node not in existing_ids:
                continue
            labels = sorted({vv.REMEDIATION_LABELS.get(s, s) for s in statuses})
            edges.append({
                'from': node_id,
                'to': asset_node,
                'title': escape('%s on %s: %s' % (first.identifier, asset_name, ', '.join(labels))),
                'dashes': False,
                'color': {'color': border},
                'kind': 'direct',
            })
