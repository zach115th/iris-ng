/* v3 case shell hydration (all 8 case tabs). Vanilla JS on purpose — the
 * shell renders inside the content block, before jQuery loads (project
 * rule). Chrome only: AI surfaces / dual timeline / imports untouched. */

function iris_cshell_esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return {'&': '&amp;', '<': '&lt;', '>': '&gt;',
                '"': '&quot;', "'": '&#39;'}[c];
    });
}

function iris_cshell_initials(name) {
    var parts = String(name || '?').trim().split(/\s+/);
    var ini = parts[0].charAt(0) + (parts.length > 1
        ? parts[parts.length - 1].charAt(0) : '');
    return ini.toUpperCase();
}

var IRIS_CSHELL = {h: null, states: null, sevs: null};

function iris_cshell_hydrate() {
    var root = document.getElementById('iris-cshell');
    if (!root) return;
    /* Case ids are digits only (server-rendered attribute) — cid is
       interpolated into the header fetch URL AND the related-alerts
       href inside an innerHTML build below, so validate before either;
       a non-numeric value means broken markup, skip hydration. */
    var cid = root.getAttribute('data-case-id') || '';
    if (!/^\d+$/.test(cid)) return;
    cid = String(parseInt(cid, 10));   /* derive: taint-free */
    fetch('/api/v2/cases/' + cid + '/header',
          {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (h) {
            if (!h) return;
            IRIS_CSHELL.h = h;
            document.getElementById('iris-cshell-name').textContent =
                h.name || '';
            var meta = [];
            if (h.client_name) {
                meta.push(iris_cshell_esc(h.client_name));
            }
            if (h.soc_id) meta.push('SOC #' + iris_cshell_esc(h.soc_id));
            if (h.owner_name) meta.push(iris_cshell_esc(h.owner_name));
            if (h.open_date) {
                meta.push('Opened ' + iris_cshell_esc(h.open_date));
            }
            if (h.close_date) {
                meta.push('Closed ' + iris_cshell_esc(h.close_date));
            }
            document.getElementById('iris-cshell-meta').innerHTML =
                meta.map(function (m) {
                    return '<span>' + m + '</span>';
                }).join('');
            document.getElementById('iris-cshell-classif').textContent =
                h.classification || '';
            var sev = document.getElementById('iris-cshell-sev');
            sev.textContent = h.severity_name || 'Unspecified';
            sev.className = 'iris-cshell-chip iris-cshell-chipbtn sev-' +
                String(h.severity_name || 'unspecified').toLowerCase();
            sev.style.display = '';
            var st = document.getElementById('iris-cshell-state');
            if (h.close_date) {
                st.textContent = 'Closed';
                st.className = 'iris-cshell-chip iris-cshell-chipbtn closed';
            } else {
                st.textContent = h.state_name || 'Open';
                st.className = 'iris-cshell-chip iris-cshell-chipbtn open';
            }
            st.style.display = '';
            /* Row 2 renders on the Summary tab only (v3) — guard every
               fill so the compact header on working tabs stays quiet. */
            ['assets', 'iocs', 'tasks', 'evidence'].forEach(function (k) {
                var el = document.getElementById('iris-cshell-c-' + k);
                if (el) {
                    el.textContent = (h.counts && h.counts[k] !== undefined)
                        ? h.counts[k] : '-';
                }
            });
            var people = document.getElementById('iris-cshell-people');
            if (people && h.people_count) {
                people.innerHTML =
                    '<span>' + h.people_count + ' people on case</span>' +
                    (h.people || []).slice(0, 6).map(function (p) {
                        return '<span class="iris-cshell-av" title="' +
                            iris_cshell_esc(p) + '">' +
                            iris_cshell_esc(iris_cshell_initials(p)) +
                            '</span>';
                    }).join('');
            }
            var right = '';
            if (h.alerts_count) {
                right += '<a class="iris-cshell-chip" style="border-color:rgba(244,196,48,0.5); color:#f4c430; text-decoration:none;" href="/alerts?cid=' +
                    cid + '&sort=desc&case_id=' + cid +
                    '" target="_blank" rel="noopener">&#9888; ' +
                    h.alerts_count + ' related alert' +
                    (h.alerts_count === 1 ? '' : 's') + '</a>';
            }
            if (h.review_status === 'Reviewed') {
                right += '<span class="iris-cshell-chip" style="border-color:rgba(45,206,137,0.5); color:#2dce89;">Reviewed' +
                    (h.reviewer_name
                        ? ' by ' + iris_cshell_esc(h.reviewer_name) : '') +
                    '</span>';
            }
            (h.tags || []).slice(0, 8).forEach(function (t) {
                right += '<span class="iris-cshell-tag">' +
                    iris_cshell_esc(t) + '</span>';
            });
            var rightEl = document.getElementById('iris-cshell-right');
            if (rightEl) rightEl.innerHTML = right;
        })
        .catch(function () { /* header stays skeletal — page still works */ });
}

function iris_cshell_close_menus() {
    document.querySelectorAll('.iris-cshell-menu').forEach(function (m) {
        m.style.display = 'none';
    });
}

function iris_cshell_toggle_menu(id) {
    var menu = document.getElementById(id);
    if (!menu) return;
    var open = menu.style.display === 'none';
    iris_cshell_close_menus();
    if (open) menu.style.display = '';
}

/* Legacy catalog fetch ({status,data} envelope — project rule). */
function iris_cshell_catalog(url, cb) {
    fetch(url, {headers: {'Accept': 'application/json'}})
        .then(function (r) { return r.json(); })
        .then(function (resp) { cb((resp && resp.data) || []); })
        .catch(function () { cb([]); });
}

function iris_cshell_put(cid, body, done) {
    fetch('/api/v2/cases/' + cid, {
        method: 'PUT',
        headers: {'Accept': 'application/json',
                  'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    }).then(function (r) {
        if (r.ok) { done(); return; }
        r.json().then(function (j) {
            window.alert((j && j.message) || 'Update failed');
        }).catch(function () { window.alert('Update failed'); });
    });
}

function iris_cshell_state_menu(cid) {
    var h = IRIS_CSHELL.h || {};
    if (h.close_date) {
        window.alert('The case is closed — reopen it from Edit Case Details first.');
        return;
    }
    var render = function () {
        document.getElementById('iris-cshell-statemenu-items').innerHTML =
            IRIS_CSHELL.states.map(function (s) {
                var cur = s.state_name === h.state_name;
                return '<a href="#" data-state-id="' + s.state_id + '" ' +
                    'data-state-name="' + iris_cshell_esc(s.state_name) +
                    '" class="' + (cur ? 'iris-cshell-current' : '') + '">' +
                    iris_cshell_esc(s.state_name) + '</a>';
            }).join('');
        iris_cshell_toggle_menu('iris-cshell-statemenu');
    };
    if (IRIS_CSHELL.states) { render(); return; }
    iris_cshell_catalog('/manage/case-states/list?cid=' + cid, function (rows) {
        IRIS_CSHELL.states = rows;
        render();
    });
}

function iris_cshell_sev_menu(cid) {
    var h = IRIS_CSHELL.h || {};
    var render = function () {
        document.getElementById('iris-cshell-sevmenu-items').innerHTML =
            IRIS_CSHELL.sevs.map(function (s) {
                var cur = s.severity_name === h.severity_name;
                return '<a href="#" data-severity-id="' + s.severity_id +
                    '" class="' + (cur ? 'iris-cshell-current' : '') + '">' +
                    iris_cshell_esc(s.severity_name) + '</a>';
            }).join('');
        iris_cshell_toggle_menu('iris-cshell-sevmenu');
    };
    if (IRIS_CSHELL.sevs) { render(); return; }
    iris_cshell_catalog('/manage/severities/list?cid=' + cid, function (rows) {
        IRIS_CSHELL.sevs = rows;
        render();
    });
}

document.addEventListener('DOMContentLoaded', function () {
    iris_cshell_hydrate();
    var root = document.getElementById('iris-cshell');
    var cid = root ? root.getAttribute('data-case-id') : null;
    var more = document.getElementById('iris-cshell-more');
    if (more) {
        more.addEventListener('click', function (e) {
            e.stopPropagation();
            iris_cshell_toggle_menu('iris-cshell-menu');
        });
    }
    /* Picking anything in the ⋮ menu closes it. Tabs promote their own actions
       into this menu (cshell_tab_menu) keeping the ids their page JS binds to,
       and those handlers used to close the tab's own section menu — which no
       longer exists. Closing here means a promoted item needs no knowledge of
       which menu it happens to be sitting in. */
    var cmenu = document.getElementById('iris-cshell-menu');
    if (cmenu) {
        cmenu.addEventListener('click', function (e) {
            if (e.target.closest('a')) iris_cshell_close_menus();
        });
    }
    var add = document.getElementById('iris-cshell-add');
    if (add) {
        add.addEventListener('click', function (e) {
            e.stopPropagation();
            iris_cshell_toggle_menu('iris-cshell-addmenu');
        });
    }
    var stateChip = document.getElementById('iris-cshell-state');
    if (stateChip) {
        stateChip.addEventListener('click', function (e) {
            e.stopPropagation();
            iris_cshell_state_menu(cid);
        });
    }
    var sevChip = document.getElementById('iris-cshell-sev');
    if (sevChip) {
        sevChip.addEventListener('click', function (e) {
            e.stopPropagation();
            iris_cshell_sev_menu(cid);
        });
    }
    var stateItems = document.getElementById('iris-cshell-statemenu-items');
    if (stateItems) {
        stateItems.addEventListener('click', function (e) {
            var a = e.target.closest('a[data-state-id]');
            if (!a) return;
            e.preventDefault();
            var h = IRIS_CSHELL.h || {};
            /* #84 reviewer-before-close gate — UI-only by maintainer
               decision, mirrored from the edit modal so this dropdown is
               not a silent bypass. */
            if (a.getAttribute('data-state-name') === 'Closed'
                    && !h.reviewer_name) {
                window.alert('A reviewer must be assigned before closing ' +
                    'this case (Edit Case Details).');
                return;
            }
            iris_cshell_put(cid,
                {state_id: parseInt(a.getAttribute('data-state-id'), 10)},
                function () { window.location.reload(); });
        });
    }
    var sevItems = document.getElementById('iris-cshell-sevmenu-items');
    if (sevItems) {
        sevItems.addEventListener('click', function (e) {
            var a = e.target.closest('a[data-severity-id]');
            if (!a) return;
            e.preventDefault();
            iris_cshell_put(cid,
                {severity_id:
                    parseInt(a.getAttribute('data-severity-id'), 10)},
                function () { window.location.reload(); });
        });
    }
    var act = document.getElementById('iris-cshell-activity');
    if (act) {
        act.addEventListener('click', function () {
            /* v3's "Live case log". This used to click the topbar bell,
               which is why pressing it lit the bell up: the bell is a FEED
               addressed to one analyst (read watermark, own edits dropped,
               "Mark as read"), while this is a LOG of what happened in the
               case, scoped to the view you are standing in. Separate
               surfaces, separate state. */
            if (window.irisCaseActivityLog) {
                window.irisCaseActivityLog.open();
            }
        });
    }
    document.addEventListener('click', function (e) {
        if (!e.target.closest('.iris-cshell-menuwrap')) {
            iris_cshell_close_menus();
        }
    });
    /* Active tab underline in the topbar strip (v3 style). */
    var path = window.location.pathname.replace(/\/+$/, '') || '/case';
    document.querySelectorAll('#h_nav_tab .nav-link').forEach(function (a) {
        var href = (a.getAttribute('href') || '').split('?')[0];
        var active = href === '/case'
            ? (path === '/case') : (href && path.indexOf(href) === 0);
        if (active) a.classList.add('iris-cnav-active');
    });
});
