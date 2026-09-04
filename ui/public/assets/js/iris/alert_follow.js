/* Alert follow star (iris-ng v2, Phase 5). Injected into the alert-details
 * expansion via the delegated shown.bs.collapse pattern - ZERO edits to
 * upstream alerts.js (the Phase 3 checklist precedent). The star markup and
 * click behaviour are shared with the topbar case star
 * (global_notifications_assets.html supplies .iris-follow-star handling and
 * window.irisFollowSetStar). Import-free: lives in ui/public. */

(function () {
    'use strict';

    var followState = null;   // {'alert:<id>': true} once loaded
    var loading = null;

    function loadFollows() {
        if (loading) { return loading; }
        loading = fetch('/api/v2/follow', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : []; })
            .then(function (list) {
                followState = {};
                (list || []).forEach(function (f) {
                    followState[f.object_type + ':' + f.object_id] = true;
                });
                return followState;
            })
            .catch(function () { followState = {}; return followState; });
        return loading;
    }

    $(document).on('shown.bs.collapse', '[id^="additionalDetails-"]', function () {
        var m = /^additionalDetails-(\d+)$/.exec(this.id);
        if (!m) { return; }
        var alertId = m[1];
        var $pane = $(this);
        if ($pane.find('.iris-alf-chip').length) { return; }
        var $chip = $('<div class="iris-alf-chip mb-1" style="font-size: 0.8rem;">'
            + '<a href="#" class="iris-follow-star" data-object-type="alert"'
            + ' data-object-id="' + alertId + '" title="Follow">&#9734;</a>'
            + ' <span class="text-muted">Follow this alert (home-page feed)</span>'
            + '</div>');
        $pane.prepend($chip);
        loadFollows().then(function (state) {
            var star = $chip.find('.iris-follow-star')[0];
            if (star && window.irisFollowSetStar) {
                window.irisFollowSetStar(star, state['alert:' + alertId]);
            }
        });
    });
})();
