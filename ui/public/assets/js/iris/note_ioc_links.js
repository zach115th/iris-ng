/* iris-ng #130 — turn IOC mentions in a note into markdown links to the IOC.
 *
 * Pure text machinery (window.IrisNoteIocLinks) so it can be driven from node
 * as well as the page:
 *
 *   linkify(text, iocs, {cid, origin, path})
 *     iocs = [{ioc_id, value, type}]  (canonical values, as the IOC table holds them)
 *     -> {text, total, linked: [{ioc_id, value, count}]}
 *
 * Rules (decided with the maintainer, 2026-09-27):
 *   - the link is the "Copy MD link" shape with the IOC VALUE as the text:
 *     [<i class="fa-solid fa-tag"></i>VALUE-AS-WRITTEN](https://host/case/ioc?cid=N&shared=ID)
 *   - defanged spellings in the note (hxxp, [.] (.) {.} [dot], [at] (at), [:])
 *     match the canonical value and are KEPT as the link text, so the note
 *     stays defanged;
 *   - a mention already inside a markdown link, an inline code span, a fenced
 *     block, an HTML tag or an autolink is left alone;
 *   - longer values win: a URL that contains a domain links as the URL and the
 *     domain inside it is not linked again; a value inside a longer hostname
 *     or hash is not a mention (boundaries);
 *   - matching is case-insensitive.
 *
 * applyToEditor(iocs, opts) is the page glue: rewrites the ACE editor's text,
 * keeps the scroll position, saves the note and (optionally) records the
 * note as a source of each linked IOC.
 */
(function (root) {
    'use strict';

    var DOT = '(?:\\.|\\[\\.\\]|\\(\\.\\)|\\{\\.\\}|\\[dot\\]|\\(dot\\))';
    var AT = '(?:@|\\[at\\]|\\(at\\)|\\[@\\])';
    var COLON = '(?::|\\[:\\])';

    function escapeRe(s) {
        return s.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&');
    }

    /* A regex source that matches the canonical value AND its usual defanged
     * spellings. Built per character so nothing but the known substitutions
     * is tolerated. */
    function tolerantSource(value) {
        var out = '';
        var v = String(value);
        var i = 0;
        var proto = /^(https?):\/\//i.exec(v);
        if (proto) {
            out += 'h(?:xx|tt)p' + (proto[1].length === 5 ? 's' : '') + COLON + '\\/\\/';
            i = proto[0].length;
        }
        for (; i < v.length; i++) {
            var ch = v[i];
            if (ch === '.') out += DOT;
            else if (ch === '@') out += AT;
            else if (ch === ':') out += COLON;
            else out += escapeRe(ch);
        }
        return out;
    }

    function boundedPattern(value) {
        /* not preceded by a word char, a dot, a dash or a defanged dot; not
         * followed by a word char, a dash, or a (defanged) dot + word char —
         * "c2.example.invalid" must not match inside
         * "x.c2.example.invalid" or "c2.example.invalid.evil". */
        var before = '(?<![\\w\\-@]|\\.|\\[\\.\\])';
        var after = '(?![\\w\\-]|\\.\\w|\\[\\.\\]\\w)';
        return new RegExp(before + tolerantSource(value) + after, 'gi');
    }

    /* Ranges of text that must not be rewritten. */
    function protectedRanges(text) {
        var ranges = [];
        var patterns = [
            /```[\s\S]*?(?:```|$)/g,                                 // fenced code
            /`[^`\n]*`/g,                                            // inline code
            /\[(?:[^\[\]]|\[[^\[\]]*\])*\]\([^)]*\)/g,               // [text](url), one nested [..] level
            /<[^>\n]*>/g,                                            // html tags / autolinks
        ];
        patterns.forEach(function (re) {
            var m;
            re.lastIndex = 0;
            while ((m = re.exec(text)) !== null) {
                if (m[0].length === 0) { re.lastIndex++; continue; }
                ranges.push([m.index, m.index + m[0].length]);
            }
        });
        return ranges;
    }

    function inProtected(ranges, start, end) {
        for (var i = 0; i < ranges.length; i++) {
            if (start < ranges[i][1] && end > ranges[i][0]) return true;
        }
        return false;
    }

    function linkFor(matched, ioc, opts) {
        var origin = opts.origin || '';
        var path = opts.path || '/case/ioc';
        return '[<i class="fa-solid fa-tag"></i>' + matched + '](' + origin + path +
               '?cid=' + opts.cid + '&shared=' + ioc.ioc_id + ')';
    }

    function linkify(text, iocs, opts) {
        opts = opts || {};
        text = String(text == null ? '' : text);
        var linked = [];
        var total = 0;
        var list = (iocs || []).filter(function (i) {
            return i && i.ioc_id && typeof i.value === 'string' && i.value.trim().length >= 3;
        }).slice().sort(function (a, b) { return b.value.length - a.value.length; });

        list.forEach(function (ioc) {
            var re = boundedPattern(ioc.value.trim());
            var ranges = protectedRanges(text);
            var out = '';
            var last = 0;
            var count = 0;
            var m;
            while ((m = re.exec(text)) !== null) {
                var start = m.index, end = start + m[0].length;
                if (m[0].length === 0) { re.lastIndex++; continue; }
                if (inProtected(ranges, start, end)) continue;
                out += text.slice(last, start) + linkFor(m[0], ioc, opts);
                last = end;
                count++;
            }
            if (count) {
                text = out + text.slice(last);
                linked.push({ioc_id: ioc.ioc_id, value: ioc.value, count: count});
                total += count;
            }
        });
        return {text: text, total: total, linked: linked};
    }

    /* ---- page glue ------------------------------------------------------ */

    function pageOpts() {
        var cid = (root.location && root.location.search.match(/[?&]cid=(\d+)/) || [])[1] || null;
        var origin = root.location ? (root.location.protocol + '//' + root.location.host) : '';
        return {cid: cid, origin: origin, path: '/case/ioc'};
    }

    function recordSource(cid, noteId, iocId, source) {
        var el = root.document && root.document.getElementById('csrf_token');
        var csrf = el ? el.value : '';
        return fetch('/api/v2/cases/' + cid + '/iocs/' + iocId + '/source-notes', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
            credentials: 'same-origin',
            body: JSON.stringify({note_id: noteId, source: source, csrf_token: csrf})
        }).catch(function () { /* provenance is auxiliary */ });
    }

    /* case.notes.js declares `let note_editor;` — a script-scope lexical
     * binding, NOT a window property, so `root.note_editor` is undefined on
     * the real page (the first browser test linked nothing). A free
     * identifier in this classic script resolves to that binding. */
    function currentEditor() {
        try {
            if (typeof note_editor !== 'undefined' && note_editor) return note_editor; // eslint-disable-line no-undef
        } catch (e) { /* not declared in this realm */ }
        return root.note_editor || null;
    }

    /* Rewrite the open note. Returns the linkify result (total 0 = nothing to
     * do, the editor is untouched and nothing is saved). */
    function applyToEditor(iocs, opts) {
        opts = opts || {};
        var editor = currentEditor();
        if (!editor || typeof editor.getValue !== 'function') return {text: '', total: 0, linked: []};
        var po = pageOpts();
        if (!po.cid) return {text: '', total: 0, linked: []};
        var res = linkify(editor.getValue(), iocs, po);
        if (!res.total) return res;
        var top = editor.session.getScrollTop();
        editor.setValue(res.text, -1);
        editor.session.setScrollTop(top);
        if (typeof root.save_note === 'function') root.save_note();
        if (opts.provenance !== false) {
            var noteId = root.jQuery ? parseInt(root.jQuery('#currentNoteIDLabel').data('note_id'), 10) : NaN;
            if (!isNaN(noteId)) {
                res.linked.forEach(function (l) { recordSource(po.cid, noteId, l.ioc_id, opts.source || 'note_link'); });
            }
        }
        return res;
    }

    /* Rows of GET /api/v2/cases/<cid>/iocs -> the matcher's shape. */
    function fromApiRows(rows) {
        return (rows || []).map(function (r) {
            return {
                ioc_id: r.ioc_id,
                value: r.ioc_value,
                type: (r.ioc_type && r.ioc_type.type_name) || r.ioc_type || null
            };
        });
    }

    root.IrisNoteIocLinks = {
        linkify: linkify,
        tolerantSource: tolerantSource,
        protectedRanges: protectedRanges,
        applyToEditor: applyToEditor,
        fromApiRows: fromApiRows,
        linkFor: linkFor
    };
})(typeof window !== 'undefined' ? window : globalThis);
