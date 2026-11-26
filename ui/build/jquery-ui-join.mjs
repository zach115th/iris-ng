// Joins the jQuery UI modules IRIS uses into one browser script, at build time (backlog #44 slice 3.6).
//
// IRIS calls only jQuery UI's draggable and resizable (modal headers, the comments panel, the notes pane, and
// atlantis.min.js's `.scroll-bar`), and touch-punch patches `$.ui.mouse`. npm's full `dist/jquery-ui.min.js` would
// also bring jQuery UI's own `tooltip` and `button` widgets - which replace Bootstrap's `$.fn.tooltip` /
// `$.fn.button` when loaded after it - and the effects that wrap `.show()`, `.hide()`, `.addClass()` and
// `.animate()` on every page. So the build takes the `ui/` modules of the npm package `jquery-ui` that these two
// widgets need, follows each module's own `define([...])` list for its dependencies, and writes them dependency
// first into one file. Each module is UMD: without an AMD loader on the page it runs `factory( jQuery )` against the
// global jQuery the layouts load first.
//
// A module that cannot be found, a dependency list that cannot be read, or a cycle stops the build.

import fs from 'node:fs';
import path from 'node:path';

const DEFINE = /define\(\s*\[([^\]]*)\]\s*,\s*factory\s*\)/;

function readDeps(source, file) {
    const m = DEFINE.exec(source);
    if (!m) {
        throw new Error(`jquery-ui-join: no define([...]) dependency list in ${file}`);
    }
    return [...m[1].matchAll(/"([^"]+)"/g)].map(d => d[1]).filter(d => d !== 'jquery');
}

// `uiDir` is the package's `ui/` folder; `entries` are module ids relative to it (e.g. 'widgets/draggable').
export function joinJqueryUi(uiDir, entries) {
    const order = [];
    const state = new Map();   // id -> 'visiting' | 'done'
    const sources = new Map();

    function visit(id, from) {
        const st = state.get(id);
        if (st === 'done') { return; }
        if (st === 'visiting') {
            throw new Error(`jquery-ui-join: dependency cycle at ${id}`);
        }
        const file = path.join(uiDir, id + '.js');
        if (!fs.existsSync(file)) {
            throw new Error(`jquery-ui-join: ${id} (needed by ${from}) not found at ${file}`);
        }
        state.set(id, 'visiting');
        const source = fs.readFileSync(file, 'utf8');
        for (const dep of readDeps(source, file)) {
            visit(path.posix.normalize(path.posix.join(path.posix.dirname(id), dep)), id);
        }
        state.set(id, 'done');
        sources.set(id, source);
        order.push(id);
    }

    for (const entry of entries) {
        visit(entry, 'the entry list');
    }
    const version = JSON.parse(fs.readFileSync(path.join(uiDir, '..', 'package.json'), 'utf8')).version;
    const head = `/*! jQuery UI ${version} - IRIS's build (ui/build/jquery-ui-join.mjs): ${order.join(', ')}\n` +
        ' * https://jqueryui.com - Copyright OpenJS Foundation and other contributors - MIT license */\n';
    const code = head + order.map(id => `/* ---- ui/${id}.js ---- */\n${sources.get(id)}`).join('\n');
    return {version, order, code};
}

// The Vite plugin: emits the joined file as a static asset at `fileName` (relative to the build's outDir).
export function jqueryUiJoinPlugin({uiDir, entries, fileName}) {
    return {
        name: 'iris-jquery-ui-join',
        generateBundle() {
            const {code} = joinJqueryUi(uiDir, entries);
            this.emitFile({type: 'asset', fileName, source: code});
        },
    };
}
