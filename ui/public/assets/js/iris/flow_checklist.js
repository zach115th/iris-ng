/* iris-ng v2 (Phase 3): shared investigation-flow checklist renderer —
 * window.IrisFlowChecklist. Renders attachments (from /alerts/<id>/flows or
 * /alert-clusters/<id>/flows) and handles step-state PUTs.
 *
 * Import-free (ui/public/). v2 envelope; csrf in the body; delegated
 * handlers with data-* read via .attr().
 */

(function () {
    'use strict';

    function esc(s) {
        return $('<div>').text(s == null ? '' : String(s)).html();
    }

    function csrf() {
        return $('#csrf_token').val();
    }

    function stateBadge(state) {
        if (state === 'done') {
            return '<span style="color: #2dce89;">&#10003;</span>';
        }
        if (state === 'skipped') {
            return '<span class="text-muted">&#8856;</span>';
        }
        return '<span class="text-muted">&#9744;</span>';
    }

    function renderAttachment(att) {
        var banner = att.required_incomplete > 0
            ? '<div class="mb-1" style="color: #f4c430; font-size: 0.8rem;">&#9888; '
              + att.required_incomplete + ' required step'
              + (att.required_incomplete === 1 ? '' : 's') + ' incomplete</div>'
            : '<div class="mb-1" style="color: #2dce89; font-size: 0.8rem;">All required steps complete</div>';
        var steps = (att.steps || []).map(function (s) {
            var who = s.done_by
                ? ' <span class="text-muted" style="font-size: 0.72rem;">'
                  + esc(s.done_by)
                  + (s.done_at ? ' · ' + esc(String(s.done_at).replace('T', ' ').slice(0, 16)) : '')
                  + '</span>'
                : '';
            var note = s.note
                ? '<div class="text-muted" style="font-size: 0.72rem; margin-left: 22px;">'
                  + esc(s.note) + '</div>'
                : '';
            return '<div class="iris-fc-step" data-attachment-id="' + att.attachment_id
                + '" data-step-id="' + s.step_id + '" data-state="' + esc(s.state)
                + '" style="cursor: pointer; padding: 2px 0;" title="click: toggle done · shift-click: skip">'
                + stateBadge(s.state) + ' '
                + (s.state === 'done'
                    ? '<span style="text-decoration: line-through; opacity: 0.7;">' + esc(s.title) + '</span>'
                    : esc(s.title))
                + (s.is_required ? ' <span style="color: #f4c430;" title="required">*</span>' : '')
                + who + note + '</div>';
        }).join('');
        return '<div class="iris-fc-attachment mb-2" data-attachment-id="' + att.attachment_id + '">'
            + '<div style="font-weight: 600;">' + esc(att.flow_name)
            + ' <span class="text-muted" style="font-size: 0.75rem;">'
            + att.steps_done + '/' + att.steps_total + '</span></div>'
            + (att.flow_description
                ? '<div class="text-muted" style="font-size: 0.75rem;">'
                  + esc(att.flow_description) + '</div>'
                : '')
            + banner + steps + '</div>';
    }

    function render(container, attachments) {
        var $c = $(container);
        if (!attachments || !attachments.length) {
            $c.html('<div class="text-muted" style="font-size: 0.8rem;">No investigation '
                + 'flows attached.</div>');
            return;
        }
        $c.html(attachments.map(renderAttachment).join(''));
    }

    function putState(attachmentId, stepId, state) {
        return fetch('/api/v2/flow-attachments/' + attachmentId + '/steps/' + stepId, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'same-origin',
            body: JSON.stringify({ state: state, csrf_token: csrf() })
        }).then(function (r) {
            return r.json().then(function (j) { j.__status = r.status; return j; });
        });
    }

    // Click toggles pending <-> done; shift-click marks skipped.
    $(document).on('click', '.iris-fc-step', function (ev) {
        var $step = $(this);
        var attId = $step.attr('data-attachment-id');
        var stepId = $step.attr('data-step-id');
        var current = $step.attr('data-state');
        var next = ev.shiftKey ? 'skipped' : (current === 'done' ? 'pending' : 'done');
        putState(attId, stepId, next).then(function (j) {
            if (j.__status !== 200) { return; }
            // Re-render just this attachment from the fresh serialization.
            var $att = $step.closest('.iris-fc-attachment');
            $att.replaceWith(renderAttachment(j));
        });
    });

    window.IrisFlowChecklist = { render: render, renderAttachment: renderAttachment };
})();
