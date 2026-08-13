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
from flask_login import current_user
from flask import Blueprint

from app.datamgmt.case.case_events_db import get_case_events_assets_graph
from app.datamgmt.case.case_events_db import get_case_events_ioc_graph
from app.datamgmt.case.case_graph_db import get_case_evidence_asset_links
from app.datamgmt.case.case_graph_db import get_case_ioc_asset_links
from app.datamgmt.case.case_graph_db import get_case_note_ioc_links
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

        if current_user.in_dark_mode:
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

    font_colour = 'white' if current_user.in_dark_mode else 'black'

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

    resp = {
        'nodes': nodes,
        'edges': edges,
        'dates': dates
    }

    return response_success("", data=resp)
