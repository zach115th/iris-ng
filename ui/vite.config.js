import { defineConfig } from "vite";
import { viteStaticCopy } from 'vite-plugin-static-copy';
import { svelte } from '@sveltejs/vite-plugin-svelte'
import { jqueryUiJoinPlugin } from './build/jquery-ui-join.mjs';

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";


function resolveInputs(directory) {
    const inputs = fs
        .readdirSync(directory, { withFileTypes: true, })
        .reduce((acc, entry) => {
            if (entry.isFile()) {
                const file = entry.name;
                const filename = path.parse(file).name;
                const filepath = path.join(directory, file);

                acc[filename] = fileURLToPath(new URL(filepath, import.meta.url));
            } else {
                const subDirectory = entry.name;
                const filepath = path.join(directory, subDirectory, 'index.js');

                if (fs.existsSync(filepath)) {
                    acc[subDirectory] = fileURLToPath(new URL(filepath, import.meta.url));
                }
            }

            return acc;
        }, {});

    return inputs;
}

export default defineConfig(({ mode }) => {
    const production = (mode === 'production');
    const development = (mode === 'development');


    return {
        build: {
            minify: false,
            manifest: false,
            outDir: 'dist',
            rollupOptions: {
                input: resolveInputs('./src/pages'),
                output: {
                    manualChunks: undefined,
                    entryFileNames: 'assets/js/iris/[name].js',
                    chunkFileNames: 'assets/js/chunks/[name]-[hash].js',
                    assetFileNames: 'assets/[ext]/[name].[ext]',
                },
                treeshake: false,
            },
            sourcemap: (development) ? 'inline': false,
        },
        resolve: {
            alias: {
                '$lib': path.resolve('./src/lib'),
            },
        },
        plugins: [
            svelte({
                emitCss: false,
                inspector: development,
            }),
            // jQuery UI: only the modules draggable and resizable need, from the npm package `jquery-ui`, joined
            // into one file (since slice 3.6; a hand-vendored 1.12.1 custom build before it). npm's full
            // dist/jquery-ui.min.js would also replace Bootstrap's $.fn.tooltip / $.fn.button and wrap .show() /
            // .hide() / .addClass() on every page - see build/jquery-ui-join.mjs.
            jqueryUiJoinPlugin({
                uiDir: 'node_modules/jquery-ui/ui',
                entries: ['widgets/draggable', 'widgets/resizable'],
                fileName: 'assets/js/plugin/jquery-ui/jquery-ui.js',
            }),
            viteStaticCopy({
                targets: [
                    // Core
                    {
                        src: 'node_modules/bootstrap/dist/js/bootstrap.min.js',
                        dest: 'assets/js/core',
                    },
                    {
                        // served as jquery.min.js since slice 3.6 (it was named jquery.3.2.1.min.js whatever
                        // version it held)
                        src: 'node_modules/jquery/dist/jquery.min.js',
                        dest: 'assets/js/core',
                    },
                    {
                        src: 'node_modules/jquery-validation/dist/jquery.validate.min.js',
                        dest: 'assets/js/core',
                        rename: 'jquery.validate.js',
                    },
                    {
                        src: 'node_modules/popper.js/dist/umd/popper.min.js',
                        dest: 'assets/js/core',
                    },
                    {
                        // the browser client from its own package (since slice 3.6; copied out of the server
                        // package `socket.io` before it - the same file)
                        src: 'node_modules/socket.io-client/dist/socket.io.min.js',
                        dest: 'assets/js/core',
                        rename: 'socket.io.js',
                    },
                    {
                        // Chart.js 4's UMD build (it sets window.Chart, as 2.x's Chart.min.js did)
                        src: 'node_modules/chart.js/dist/chart.umd.min.js',
                        dest: 'assets/js/core',
                        rename: 'charts.js',
                    },
                    // Plugins
                    {
                        // The OFFICIAL minified build of the same ace-builds
                        // version, renamed so the template URLs (hardcoded to
                        // .../ace/src-noconflict/) stay untouched. ace.js goes
                        // 886K -> 464K, which is mostly parse-time on every
                        // case page; modes/themes/workers ship in both dirs.
                        src: 'node_modules/ace-builds/src-min-noconflict/',
                        dest: 'assets/js/plugin/ace/',
                        rename: 'src-noconflict',
                    },
                    // DataTables 3 (since slice 3.5; 1.10.16 hand-vendored before it): the core with its Bootstrap 4
                    // integration (the paging markup and classes; 1.10.16's Bootstrap 4 stylesheet is part of
                    // atlantis.css, so the integration's own stylesheet is not copied) and the extensions. Buttons keeps
                    // its Bootstrap 4 stylesheet, as before (its scripts stay the default ones, so a button is a
                    // dt-button with the page's own btn classes); Select 4, Responsive 4 and RowGroup 2 redrew their
                    // look, so css/datatables_compat.{select,responsive,rowgroup}.css carry their 1.10.16-era
                    // stylesheets instead. iris/datatables_compat.js gives the pages 1.10.16's class names, layout,
                    // texts, ordering and column widths.
                    {
                        src: 'node_modules/datatables.net/js/dataTables.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        src: 'node_modules/datatables.net-bs4/js/dataTables.bootstrap4.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        // Buttons 4 carries the copy / CSV / column-visibility buttons itself
                        src: 'node_modules/datatables.net-buttons/js/dataTables.buttons.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        src: 'node_modules/datatables.net-responsive/js/dataTables.responsive.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        src: 'node_modules/datatables.net-select/js/dataTables.select.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        src: 'node_modules/datatables.net-rowgroup/js/dataTables.rowGroup.min.js',
                        dest: 'assets/js/plugin/datatables/',
                    },
                    {
                        src: 'node_modules/datatables.net-buttons-bs4/css/buttons.bootstrap4.min.css',
                        dest: 'assets/css/',
                    },
                    {
                        // dropzone 6 dropped dist/min/; its browser build is
                        // dist/dropzone-min.js. Shipped under the name the
                        // pipelines modal actually loads (dropzone.js) - the
                        // old dropzone.min.js copy was never referenced by any
                        // template, so the modal's script tag 404'd before
                        // this copy. A second copy under the old name, kept
                        // for anything external, went on 2026-11-25: nothing
                        // loaded it.
                        src: 'node_modules/dropzone/dist/dropzone-min.js',
                        dest: 'assets/js/plugin/dropzone/',
                        rename: 'dropzone.js',
                    },
                    {
                        // "Export page as PNG" (exportInnerPng() in iris/common.js loads it on first click); since
                        // slice 3.6, html2canvas 1.4.1 (no release since 2022) before it. Its browser build sets
                        // window.html2canvas to the same function.
                        src: 'node_modules/html2canvas-pro/dist/html2canvas-pro.min.js',
                        dest: 'assets/js/plugin/html2canvas-pro/',
                    },
                    // The select widgets, from npm since slice 3.6 (hand-vendored before it: select2 4.1.0-beta.1,
                    // bootstrap-select 1.13.9, ajax-bootstrap-select 1.4.5), under the names the templates load.
                    // select2's full build, as before (the case pages' select2 calls).
                    {
                        src: 'node_modules/select2/dist/js/select2.full.min.js',
                        dest: 'assets/js/plugin/select/',
                        rename: 'select2.js',
                    },
                    {
                        src: 'node_modules/select2/dist/css/select2.min.css',
                        dest: 'assets/css/',
                        rename: 'select2.css',
                    },
                    {
                        src: 'node_modules/bootstrap-select/dist/js/bootstrap-select.min.js',
                        dest: 'assets/js/plugin/select/',
                    },
                    {
                        src: 'node_modules/bootstrap-select/dist/css/bootstrap-select.min.css',
                        dest: 'assets/css/',
                    },
                    {
                        // the case switcher (#user_context) and the alerts page's merge-into-case picker
                        src: 'node_modules/ajax-bootstrap-select/dist/js/ajax-bootstrap-select.min.js',
                        dest: 'assets/js/plugin/select/',
                        rename: 'ajax-bootstrap-picker.js',
                    },
                    {
                        src: 'node_modules/jquery.scrollbar/jquery.scrollbar.min.js',
                        dest: 'assets/js/plugin/jquery-scrollbar/',
                    },
                    {
                        src: 'node_modules/jquery-ui-touch-punch/jquery.ui.touch-punch.min.js',
                        dest: 'assets/js/plugin/jquery-ui-touch-punch/',
                    },
                    {
                        src: 'node_modules/marked/lib/marked.umd.js',
                        dest: 'assets/js/plugin/marked/',
                        rename: 'marked.min.js',
                    },
                    {
                        // sweetalert2 draws every dialog; iris/swal_compat.js gives it 2.1.2's swal() API and
                        // css/swal_compat.css 2.1.2's look (since slice 3.3; 2.1.2 itself is gone)
                        src: 'node_modules/sweetalert2/dist/sweetalert2.min.js',
                        dest: 'assets/js/plugin/sweetalert2/',
                    },
                    {
                        src: 'node_modules/sweetalert2/dist/sweetalert2.min.css',
                        dest: 'assets/css/',
                    },
                    {
                        // the Evidence page's in-browser MD5 (getMD5() in iris/case.rfiles.js; since slice 3.4,
                        // CryptoJS 3.1.2 before it)
                        src: 'node_modules/spark-md5/spark-md5.min.js',
                        dest: 'assets/js/plugin/spark-md5/',
                    },
                    {
                        src: 'node_modules/vis-network/standalone/umd/vis-network.min.js',
                        dest: 'assets/js/plugin/vis/',
                    },
                    {
                        src: 'node_modules/vis-timeline/standalone/umd/vis-timeline-graph2d.min.js',
                        dest: 'assets/js/plugin/vis/',
                        rename: 'vis.graph.js'
                    },
                    {
                        src: 'node_modules/xss/dist/xss.min.js',
                        dest: 'assets/js/plugin/xss/',
                        rename: 'xss.js',
                    },
                ]
            }),
        ],
    }
});
