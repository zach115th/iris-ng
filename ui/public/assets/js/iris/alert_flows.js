/* iris-ng v2 (Phase 3): checklist panel inside the Alerts page's per-alert
 * detail expansion. Deliberately ZERO edits to alerts.js: the expansion
 * container is #additionalDetails-<alert_id> (Bootstrap collapse), so a
 * delegated shown.bs.collapse listener injects/refreshes a checklist
 * section whenever a detail pane opens. Robust to upstream alerts.js churn.
 *
 * Import-free (ui/public/). Requires flow_checklist.js.
 */

(function () {
    'use strict';

    function loadInto(alertId, $container) {
        fetch('/api/v2/alerts/' + alertId + '/flows', { credentials: 'same-origin' })
            .then(function (r) { return r.status === 200 ? r.json() : []; })
            .then(function (atts) {
                if (!atts || !atts.length) {
                    // No flows: leave the expansion untouched (no empty box
                    // on every alert — the section only appears when there
                    // is a checklist to show).
                    $container.remove();
                    return;
                }
                window.IrisFlowChecklist.render(
                    $container.find('.iris-af-body')[0], atts);
            })
            .catch(function () { $container.remove(); });
    }

    $(document).on('shown.bs.collapse', '[id^="additionalDetails-"]', function () {
        var m = /^additionalDetails-(\d+)$/.exec(this.id);
        if (!m) { return; }
        var alertId = m[1];
        var $pane = $(this);
        var $existing = $pane.find('.iris-af-section');
        if (!$existing.length) {
            $existing = $('<div class="iris-af-section card mt-2 mb-2"><div class="card-body py-2">'
                + '<h6 class="mb-1">Investigation flows</h6>'
                + '<div class="iris-af-body text-muted" style="font-size: 0.8rem;">Loading…</div>'
                + '</div></div>');
            $pane.prepend($existing);
        }
        loadInto(alertId, $existing);
    });
})();
