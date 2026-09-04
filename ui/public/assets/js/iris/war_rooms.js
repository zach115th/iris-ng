/* War Rooms list page (iris-ng v2, Phase 6; v3-shaped card grid).
 * Import-free by rule (Vite copies ui/public verbatim; rolldown drops
 * inline-handler-only functions from ui/src). All data from /api/v2.
 * The API returns EVERY status; chips + search filter client-side. */

var IRIS_WR = {
    /* cid reaches innerHTML (discovery "Open room" link) and navigation
       URLs — it must be a case id, so anything non-numeric falls back
       to '1' instead of reaching a sink. */
    _cid: (function () {
        var v = new URLSearchParams(window.location.search).get('cid');
        return /^\d+$/.test(v || '') ? v : '1';
    })(),
    _rooms: [],
    _chip: '',
    _q: ''
};

function iris_wr_esc(s) {
    return String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function iris_wr_csrf() {
    var el = document.getElementById('csrf_token');
    return el ? el.value : '';
}

function iris_wr_created(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return 'Created ' + (d.getMonth() + 1) + '/' + d.getDate() + '/' +
        d.getFullYear();
}

function iris_wr_render() {
    var rooms = IRIS_WR._rooms.filter(function (r) {
        if (IRIS_WR._chip && r.status !== IRIS_WR._chip) return false;
        if (IRIS_WR._q) {
            var hay = ((r.name || '') + ' ' + (r.description || ''))
                .toLowerCase();
            if (hay.indexOf(IRIS_WR._q) === -1) return false;
        }
        return true;
    });
    var grid = document.getElementById('iris-wr-cards');
    var empty = document.getElementById('iris-wr-empty');
    grid.innerHTML = '';
    if (!rooms.length) {
        /* Say WHY it is empty (none-vs-broken rule). */
        empty.textContent = IRIS_WR._rooms.length
            ? 'No rooms match the current filter.'
            : 'No war rooms yet. Create one, or ask a lead to add you.';
        empty.style.display = '';
        return;
    }
    empty.style.display = 'none';
    rooms.forEach(function (r) {
        var col = document.createElement('div');
        col.className = 'col-md-4 mb-3';
        var meta = r.member_count + ' member' + (r.member_count === 1 ? '' : 's')
            + ' · ' + r.case_count + ' case'
            + (r.case_count === 1 ? '' : 's')
            + (r.my_role ? ' · ' + r.my_role : '');
        col.innerHTML =
            '<div class="iris-wr-card" data-room-id="' + r.id + '">' +
            '<div style="display:flex; align-items:flex-start;">' +
            '<div class="iris-wr-card-title">' +
            (r.status === 'open' ? '<span class="iris-wr-open-dot"></span>' : '') +
            iris_wr_esc(r.name) + '</div>' +
            '<span class="iris-wr-badge iris-wr-badge-' + r.status +
            '" style="margin-left:auto;">' + r.status + '</span></div>' +
            '<div class="iris-wr-card-desc">' +
            iris_wr_esc(r.description || '') + '</div>' +
            '<div class="iris-wr-card-foot"><span>' +
            iris_wr_created(r.created_at) + '</span>' +
            '<span style="margin-left:auto;">' + iris_wr_esc(meta) +
            '</span></div></div>';
        grid.appendChild(col);
    });
}

function iris_wr_load() {
    fetch('/api/v2/war-rooms', {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (data) {
            IRIS_WR._rooms = data.rooms || [];
            iris_wr_render();
        });
}

/* ------------------------------------------------- discovery panel */

function iris_wr_load_discovery() {
    var minShared = parseInt(
        document.getElementById('iris-wr-disc-minshared').value, 10) || 2;
    Promise.all([
        fetch('/api/v2/correlation/report?min_shared=' + minShared,
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); }),
        fetch('/api/v2/war-rooms/promoted-clusters',
              {headers: {'Accept': 'application/json'}})
            .then(function (r) { return r.json(); })
    ]).then(function (results) {
        var report = results[0] || {};
        var promoted = (results[1] && results[1].promoted) || {};
        var clusters = report.clusters || [];
        var meta = report.case_meta || {};
        var box = document.getElementById('iris-wr-disc-list');
        document.getElementById('iris-wr-disc-empty').style.display =
            clusters.length ? 'none' : '';
        box.innerHTML = '';
        clusters.forEach(function (cl) {
            var caseBits = cl.case_ids.map(function (cid) {
                var m = meta[cid] || meta[String(cid)] || {};
                return '<a href="/case?cid=' + cid + '">#' + cid + '</a> ' +
                    iris_wr_esc(m.name || '');
            }).join(' · ');
            var roomId = promoted[cl.cluster_id];
            var action = roomId
                ? '<a class="btn btn-sm btn-secondary" href="/war-rooms/' +
                  roomId + '?cid=' + IRIS_WR._cid + '">Open room #' + roomId + '</a>'
                : '<button class="btn btn-sm btn-primary iris-wr-promote" ' +
                  'data-cluster-id="' + iris_wr_esc(cl.cluster_id) + '">' +
                  'Promote to war room</button>';
            var div = document.createElement('div');
            div.className = 'mb-3 p-2';
            div.style.cssText = 'border: 1px solid rgba(139,92,246,0.25);' +
                'border-radius: 8px; background: rgba(139,92,246,0.05);';
            div.innerHTML =
                '<div style="display:flex; align-items:center;">' +
                '<div style="flex:1 1 auto; min-width:0;">' +
                '<span class="iris-wr-campaign-chip">' +
                iris_wr_esc(cl.cluster_id) + '</span> ' +
                '<strong>' + cl.case_ids.length + ' cases</strong> · ' +
                cl.shared_ioc_count + ' shared IOC(s)' +
                '<div class="text-muted" style="font-size:0.8rem;">' +
                caseBits + '</div></div>' +
                '<div style="flex-shrink:0;">' + action + '</div></div>';
            box.appendChild(div);
        });
    });
}

document.addEventListener('DOMContentLoaded', function () {
    iris_wr_load();
    iris_wr_load_discovery();

    document.getElementById('iris-wr-chips')
        .addEventListener('click', function (e) {
            var chip = e.target.closest('.iris-wr-chip');
            if (!chip) return;
            IRIS_WR._chip = chip.getAttribute('data-status') || '';
            document.querySelectorAll('#iris-wr-chips .iris-wr-chip')
                .forEach(function (c) { c.classList.remove('active'); });
            chip.classList.add('active');
            iris_wr_render();
        });

    document.getElementById('iris-wr-search')
        .addEventListener('input', function () {
            IRIS_WR._q = this.value.trim().toLowerCase();
            iris_wr_render();
        });

    document.getElementById('iris-wr-cards')
        .addEventListener('click', function (e) {
            var card = e.target.closest('.iris-wr-card');
            if (!card) return;
            window.location.href = '/war-rooms/' +
                card.getAttribute('data-room-id') + '?cid=' + IRIS_WR._cid;
        });

    document.getElementById('iris-wr-new-btn')
        .addEventListener('click', function () {
            document.getElementById('iris-wr-new-name').value = '';
            document.getElementById('iris-wr-new-desc').value = '';
            document.getElementById('iris-wr-new-error').style.display = 'none';
            $('#iris-wr-new-modal').modal('show');
        });

    document.getElementById('iris-wr-new-save')
        .addEventListener('click', function () {
            var body = {
                name: document.getElementById('iris-wr-new-name').value,
                description: document.getElementById('iris-wr-new-desc').value,
                csrf_token: iris_wr_csrf()
            };
            fetch('/api/v2/war-rooms', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)
            }).then(function (r) {
                return r.json().then(function (j) { return {ok: r.ok, j: j}; });
            }).then(function (res) {
                if (!res.ok) {
                    var err = document.getElementById('iris-wr-new-error');
                    err.textContent = res.j.message || 'Failed to create room';
                    err.style.display = '';
                    return;
                }
                window.location.href = '/war-rooms/' + res.j.id +
                    '?cid=' + IRIS_WR._cid;
            });
        });

    document.getElementById('iris-wr-disc-refresh')
        .addEventListener('click', iris_wr_load_discovery);
    document.getElementById('iris-wr-disc-list')
        .addEventListener('click', function (e) {
            var btn = e.target.closest('.iris-wr-promote');
            if (!btn) return;
            btn.disabled = true;
            var minShared = parseInt(
                document.getElementById('iris-wr-disc-minshared').value, 10) || 2;
            fetch('/api/v2/war-rooms/promote-cluster', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    cluster_id: btn.getAttribute('data-cluster-id'),
                    min_shared: minShared,
                    csrf_token: iris_wr_csrf()
                })
            }).then(function (r) {
                return r.json().then(function (j) {
                    return {ok: r.ok, status: r.status, j: j};
                });
            }).then(function (res) {
                if (res.ok) {
                    window.location.href = '/war-rooms/' + res.j.id +
                        '?cid=' + IRIS_WR._cid;
                } else if (res.status === 409 && res.j.room_id) {
                    window.location.href = '/war-rooms/' + res.j.room_id +
                        '?cid=' + IRIS_WR._cid;
                } else {
                    btn.disabled = false;
                    alert(res.j.message || 'Promote failed');
                }
            });
        });
});
