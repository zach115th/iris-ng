/* iris-ng v2: deep-link auto-expand on the Alerts page (2026-09-01).
 *
 * When the page is filtered to exactly ONE alert (?alert_ids=<id> with a
 * single id — the shape every per-alert deep link produces: cluster Alerts
 * tab, notifications, correlation drawer), the visitor came to SEE that
 * alert, so its detail pane opens by itself. Multi-id links (a cluster's
 * "Open in Alerts view") keep the collapsed list — that is a browsing view.
 *
 * ZERO edits to upstream alerts.js (same discipline as alert_flows.js):
 * the pane is #additionalDetails-<id> (Bootstrap collapse), rendered
 * asynchronously after the alerts fetch, so a MutationObserver waits for it
 * and fires .collapse('show') exactly once. Opening through the real
 * collapse API means shown.bs.collapse fires and the checklist injection
 * runs, exactly as for a manual click.
 *
 * Import-free (ui/public/ — verbatim copy, no rolldown pass).
 */

(function () {
    'use strict';

    var ids = (new URLSearchParams(window.location.search).get('alert_ids') || '')
        .split(',').map(function (s) { return s.trim(); }).filter(Boolean);
    if (ids.length !== 1 || !/^\d+$/.test(ids[0])) { return; }
    var paneId = 'additionalDetails-' + ids[0];
    var done = false;

    function expandIfPresent() {
        if (done) { return true; }
        var pane = document.getElementById(paneId);
        if (!pane) { return false; }
        done = true;
        // Defer one tick so alerts.js has finished wiring the card this
        // render pass; .collapse('show') is a no-op on an already-open pane.
        setTimeout(function () {
            $('#' + paneId).collapse('show');
            // A manual title click ALSO fires fetchSmartRelations (alerts.js
            // line ~918) — mirror it so the deep-link expansion is
            // click-identical. typeof guard: the global lives in alerts.js.
            if (typeof window.fetchSmartRelations === 'function') {
                window.fetchSmartRelations(parseInt(ids[0], 10));
            }
            var card = pane.closest('.card') || pane;
            if (card.scrollIntoView) {
                card.scrollIntoView({ behavior: 'smooth', block: 'start' });
            }
        }, 50);
        return true;
    }

    document.addEventListener('DOMContentLoaded', function () {
        if (expandIfPresent()) { return; }
        var observer = new MutationObserver(function () {
            if (expandIfPresent()) { observer.disconnect(); }
        });
        observer.observe(document.body, { childList: true, subtree: true });
        // The alert may not exist / not be visible to this user — stop
        // watching after 20s rather than observing forever.
        setTimeout(function () { observer.disconnect(); }, 20000);
    });
})();
