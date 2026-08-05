
/* Case knowledge map.
 *
 * The graph data carries a `layer` tag on every node ('asset' | 'ioc' |
 * 'note' | 'evidence') and a `kind` on every edge ('event' for timeline
 * co-occurrence, 'direct' for M2M link-table relationships). The layer
 * toggles filter client-side against the last fetched payload, so flipping a
 * layer never re-hits the API.
 */

var network;
var _graphData = { nodes: [], edges: [] };

const IRIS_GRAPH_LAYERS = ['asset', 'ioc', 'note', 'evidence'];
const IRIS_GRAPH_LAYER_KEY = 'irisGraphLayers';

/* Layers default to all-on, so the graph looks exactly like it always did
 * until the analyst turns something off. */
function irisGraphLoadLayerState() {
    let state = {};
    IRIS_GRAPH_LAYERS.forEach(l => { state[l] = true; });
    try {
        const saved = JSON.parse(localStorage.getItem(IRIS_GRAPH_LAYER_KEY) || '{}');
        IRIS_GRAPH_LAYERS.forEach(l => {
            if (typeof saved[l] === 'boolean') state[l] = saved[l];
        });
    } catch (e) { /* corrupt value -> fall back to all-on */ }
    return state;
}

function irisGraphSaveLayerState(state) {
    try {
        localStorage.setItem(IRIS_GRAPH_LAYER_KEY, JSON.stringify(state));
    } catch (e) { /* private mode / quota -> filtering still works this session */ }
}

function irisGraphActiveLayers() {
    const state = irisGraphLoadLayerState();
    IRIS_GRAPH_LAYERS.forEach(l => {
        const cb = document.getElementById('iris-graph-layer-' + l);
        if (cb) state[l] = cb.checked;
    });
    return state;
}

/* Filter the cached payload down to the enabled layers. An edge survives only
 * if BOTH endpoints survive -- otherwise vis.js would render a dangling edge. */
function irisGraphFilter(data, state) {
    const nodes = (data.nodes || []).filter(n => {
        const layer = n.layer;
        if (!layer) return true;            // untagged -> always show
        return state[layer] !== false;
    });
    const visible = new Set(nodes.map(n => n.id));
    const edges = (data.edges || []).filter(e => visible.has(e.from) && visible.has(e.to));
    return { nodes: nodes, edges: edges };
}

function irisGraphRender(data) {
    const container = document.getElementById('graph-container');
    if (!container) return;

    const options = {
        edges: {
            smooth: { enabled: true, type: 'continuous', roundness: 0.5 }
        },
        layout: { randomSeed: 2, improvedLayout: true },
        interaction: { hideEdgesOnDrag: false },
        width: (window.innerWidth - 400) + 'px',
        height: (window.innerHeight - 250) + 'px',
        physics: {
            forceAtlas2Based: {
                gravitationalConstant: -167,
                centralGravity: 0.04,
                springLength: 0,
                springConstant: 0.02,
                damping: 0.9
            },
            minVelocity: 0.41,
            solver: 'forceAtlas2Based',
            timestep: 0.45
        }
    };

    network = new vis.Network(container, data, options);
    network.on('stabilizationIterationsDone', function () {
        network.setOptions({ physics: false });
    });
}

/* Re-filter and redraw from the cached payload -- no API call. */
function irisGraphApplyLayers() {
    const state = irisGraphActiveLayers();
    irisGraphSaveLayerState(state);

    const filtered = irisGraphFilter(_graphData, state);
    irisGraphUpdateCounts(filtered);

    const container = document.getElementById('graph-container');
    if (filtered.nodes.length === 0) {
        if (network) { network.destroy(); network = null; }
        if (container) container.textContent = 'No nodes match the selected layers';
        return;
    }
    if (container) container.textContent = '';
    irisGraphRender(filtered);
}

function irisGraphUpdateCounts(filtered) {
    const el = document.getElementById('iris-graph-counts');
    if (el) {
        el.textContent = filtered.nodes.length + ' nodes / ' + filtered.edges.length + ' links';
    }
}

function redrawAll(data) {
    _graphData = data || { nodes: [], edges: [] };

    if (!_graphData.nodes || _graphData.nodes.length === 0) {
        $('#card_main_load').show();
        $('#graph-container').text('No events in graph');
        hide_loader();
        return true;
    }

    $('#card_main_load').show();
    irisGraphApplyLayers();
    hide_loader();
}

function get_case_graph() {
    get_request_api('graph/getdata')
        .done((data) => {
            if (data.status == 'success') {
                redrawAll(data.data);
                hide_loader();
            } else {
                $('#submit_new_asset').text('Save again');
                swal("Oh no !", data.message, "error")
            }
        })
}

/* Page is ready, fetch the assets of the case */
$(document).ready(function () {
    const state = irisGraphLoadLayerState();
    IRIS_GRAPH_LAYERS.forEach(l => {
        const cb = document.getElementById('iris-graph-layer-' + l);
        if (cb) {
            cb.checked = state[l];
            cb.addEventListener('change', irisGraphApplyLayers);
        }
    });
    get_case_graph();
});
